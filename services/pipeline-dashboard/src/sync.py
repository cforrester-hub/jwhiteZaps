"""Background data sync from AgencyZoom to local PostgreSQL cache."""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import json as json_module

from sqlalchemy import delete, select, text

from .az_client import (
    _rate_limit_delay,
    fetch_all_leads_for_pipeline,
    fetch_employees,
    fetch_lead_detail,
    fetch_lead_files,
    fetch_lead_quotes,
    fetch_pipelines_and_stages,
    system_login,
)
from .config import get_settings
from .database import Employee, Lead, LeadFile, LeadOpportunity, LeadQuote, Pipeline, Stage, SyncMeta, async_session

PACIFIC = ZoneInfo("America/Los_Angeles")


def _convert_az_date(date_str: str | None) -> str | None:
    """Convert an AZ date string from the agency's timezone to Pacific.

    AZ returns naive datetimes like "2026-03-20 14:30:00" in the agency's
    configured timezone. We parse, localize, convert to Pacific, and return
    as a string in the same format.
    """
    if not date_str or len(date_str) < 10:
        return date_str
    settings = get_settings()
    az_tz = ZoneInfo(settings.az_timezone)
    # If AZ timezone is already Pacific, no conversion needed
    if settings.az_timezone == "America/Los_Angeles":
        return date_str
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=az_tz).astimezone(PACIFIC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return date_str

logger = logging.getLogger(__name__)

sync_in_progress = False
sync_started_at: float | None = None


async def sync_all(_manual: bool = False):
    """Main sync job: fetch pipelines, stages, and leads from AgencyZoom."""
    global sync_in_progress, sync_started_at
    if sync_in_progress and not _manual:
        logger.info("Sync already in progress, skipping")
        return
    sync_in_progress = True
    sync_started_at = sync_started_at or time.monotonic()
    try:
        await _sync_all_inner()
    finally:
        sync_in_progress = False
        sync_started_at = None


async def _get_last_successful_sync() -> datetime | None:
    """Get the timestamp of the last successful sync from the DB."""
    async with async_session() as session:
        result = await session.execute(
            select(SyncMeta).where(SyncMeta.key == "last_successful_sync")
        )
        meta = result.scalar_one_or_none()
        if meta and meta.value:
            try:
                return datetime.strptime(meta.value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    return None


async def _set_last_successful_sync(ts: datetime):
    """Record the timestamp of a successful sync."""
    async with async_session() as session:
        async with session.begin():
            await session.merge(SyncMeta(
                key="last_successful_sync",
                value=ts.strftime("%Y-%m-%d %H:%M:%S"),
                updated_at=ts,
            ))


async def _sync_all_inner():
    """Inner sync logic."""
    sync_start = datetime.utcnow()

    # Determine if this is a full or delta sync
    last_sync = await _get_last_successful_sync()
    is_delta = last_sync is not None
    delta_date_filter = None
    if is_delta:
        # Look back 24 hours from last successful sync to catch anything we missed
        lookback = last_sync - timedelta(hours=24)
        delta_date_filter = lookback.strftime("%Y-%m-%d")

    sync_type = "delta" if is_delta else "full"
    logger.info(f"Starting {sync_type} pipeline data sync"
                + (f" (activity since {delta_date_filter})" if delta_date_filter else ""))

    # Check if a detail backfill has been requested
    needs_detail_backfill = False
    async with async_session() as session:
        result = await session.execute(
            select(SyncMeta).where(SyncMeta.key == "detail_backfill_needed")
        )
        meta = result.scalar_one_or_none()
        if meta and meta.value == "true":
            needs_detail_backfill = True
            logger.info("Detail backfill flag detected — will sync details for ALL leads")

    try:
        jwt = await system_login()
    except Exception as e:
        logger.error(f"Sync failed: could not authenticate - {e}")
        return

    # Step 1: Sync pipelines and stages (always full)
    try:
        pipelines_data = await fetch_pipelines_and_stages(jwt)
        logger.info(f"Fetched {len(pipelines_data)} pipelines from AgencyZoom")
    except Exception as e:
        logger.error(f"Sync failed: could not fetch pipelines - {e}")
        return

    async with async_session() as session:
        async with session.begin():
            # Upsert pipelines and stages
            pipeline_ids = set()
            stage_ids = set()

            for p in pipelines_data:
                pid = str(p.get("id", ""))
                if not pid:
                    continue
                pipeline_ids.add(pid)

                await session.merge(Pipeline(
                    id=pid,
                    name=p.get("name", ""),
                    type=p.get("type"),
                    seq=p.get("seq"),
                    status=p.get("status"),
                    synced_at=sync_start,
                ))

                for s in p.get("stages", []):
                    sid = str(s.get("id", ""))
                    if not sid:
                        continue
                    stage_ids.add(sid)

                    await session.merge(Stage(
                        id=sid,
                        pipeline_id=pid,
                        name=s.get("name", ""),
                        seq=s.get("seq"),
                        status=s.get("status"),
                        synced_at=sync_start,
                    ))

            # Delete pipelines/stages no longer in AZ
            if pipeline_ids:
                await session.execute(
                    delete(Stage).where(Stage.id.notin_(stage_ids))
                )
                await session.execute(
                    delete(Pipeline).where(Pipeline.id.notin_(pipeline_ids))
                )

    await _rate_limit_delay()

    # Build pipeline/stage name lookups from synced pipeline data
    pipeline_names = {}
    stage_names = {}
    for p in pipelines_data:
        pipeline_names[str(p.get("id", ""))] = p.get("name", "")
        for s in p.get("stages", []):
            stage_names[str(s.get("id", ""))] = s.get("name", "")

    # Step 2: Sync leads per pipeline
    # For full sync, limit to last 12 months of activity
    if not is_delta and not delta_date_filter:
        twelve_months_ago = (sync_start - timedelta(days=365)).strftime("%Y-%m-%d")
        delta_date_filter = twelve_months_ago
        logger.info(f"Full sync: limiting to leads with activity since {delta_date_filter}")

    total_leads = 0
    synced_pipeline_ids = []  # Track successful syncs for safe stale deletion
    for p in pipelines_data:
        pid = p.get("id")
        if pid is None:
            continue

        try:
            # Convert to int for the API call (workflowId expects integer)
            pipeline_int_id = int(pid)
            leads = await fetch_all_leads_for_pipeline(
                jwt, pipeline_int_id,
                last_activity_earliest_date=delta_date_filter,
            )
            logger.info(f"Pipeline '{p.get('name')}' (id={pid}): {len(leads)} leads")
            synced_pipeline_ids.append(str(pid))
        except Exception as e:
            logger.error(f"Failed to sync leads for pipeline {pid}: {e}")
            continue

        async with async_session() as session:
            async with session.begin():
                for lead in leads:
                    lead_id = lead.get("id")
                    if lead_id is None:
                        continue

                    # Use lead's own workflowId if available, fall back to loop pipeline
                    lead_pipeline_id = str(lead.get("workflowId") or pid)
                    lead_stage_id = str(lead.get("workflowStageId", ""))

                    await session.merge(Lead(
                        id=lead_id,
                        pipeline_id=lead_pipeline_id,
                        stage_id=lead_stage_id,
                        assigned_to=lead.get("assignedTo"),
                        firstname=lead.get("firstname"),
                        lastname=lead.get("lastname"),
                        lead_type=lead.get("leadType"),
                        phone=lead.get("phone"),
                        email=lead.get("email"),
                        status=lead.get("status"),
                        premium=lead.get("premium"),
                        quoted=lead.get("quoted"),
                        enter_stage_date=_convert_az_date(lead.get("enterStageDate")),
                        last_activity_date=_convert_az_date(lead.get("lastActivityDate")),
                        contact_date=_convert_az_date(lead.get("contactDate")),
                        lead_source_name=lead.get("leadSourceName"),
                        # Resolve names: prefer lead data, fall back to pipeline/stage lookup
                        workflow_name=lead.get("workflowName") or pipeline_names.get(lead_pipeline_id),
                        workflow_stage_name=lead.get("workflowStageName") or stage_names.get(lead_stage_id),
                        assign_to_firstname=lead.get("assignToFirstname"),
                        assign_to_lastname=lead.get("assignToLastname"),
                        # High-value columns
                        street_address=lead.get("streetAddress"),
                        city=lead.get("city"),
                        state=lead.get("state"),
                        zip_code=lead.get("zip"),
                        sold_date=_convert_az_date(lead.get("soldDate")),
                        x_date=_convert_az_date(lead.get("xDate")),
                        quote_date=_convert_az_date(lead.get("quoteDate")),
                        customer_id=lead.get("customerId"),
                        tag_names=",".join(lead["tagNames"]) if isinstance(lead.get("tagNames"), list) else lead.get("tagNames"),
                        lead_source_id=lead.get("leadSourceId"),
                        raw_json=lead,
                        synced_at=sync_start,
                    ))

                total_leads += len(leads)

        await _rate_limit_delay()

    # Step 2.5: Sync lead details (quotes, opportunities via detail endpoint; files via separate call)
    # Only fetch details for leads likely to have quotes (saves thousands of API calls)
    quote_likely_filter = or_(
        Lead.quote_date != None,
        Lead.quoted != None,
        Lead.premium != None,
        Lead.status == 2,  # WON — must have been quoted
    )

    async with async_session() as session:
        if needs_detail_backfill:
            # Full backfill: leads likely to have quotes that haven't been detail-synced
            query = select(Lead).where(
                quote_likely_filter,
                (Lead.detail_synced_at == None) | (Lead.detail_synced_at < sync_start),
            )
        elif is_delta:
            # Delta: only leads updated in this sync cycle that are likely to have quotes
            query = select(Lead).where(
                Lead.synced_at >= sync_start,
                quote_likely_filter,
            )
        else:
            # Full sync: all leads likely to have quotes
            query = select(Lead).where(quote_likely_filter)

        result = await session.execute(query)
        leads_needing_detail = result.scalars().all()

    logger.info(f"Syncing details for {len(leads_needing_detail)} leads (filtered to quote-likely)")

    detail_success = 0
    detail_errors = 0
    for lead in leads_needing_detail:
        try:
            detail = await fetch_lead_detail(jwt, lead.id)

            async with async_session() as session:
                async with session.begin():
                    # Store full detail response and timestamp
                    await session.execute(
                        text("UPDATE pd_leads SET detail_json = :dj, detail_synced_at = :ds WHERE id = :lid"),
                        {"dj": json_module.dumps(detail), "ds": sync_start, "lid": lead.id},
                    )

            # Fetch quotes via dedicated endpoint (has carrierName, productName)
            try:
                quotes = await fetch_lead_quotes(jwt, lead.id)
                async with async_session() as session:
                    async with session.begin():
                        await session.execute(
                            delete(LeadQuote).where(LeadQuote.lead_id == lead.id)
                        )
                        for q in quotes:
                            q_id = q.get("id")
                            if q_id is None:
                                continue
                            await session.merge(LeadQuote(
                                id=q_id,
                                lead_id=lead.id,
                                carrier_id=q.get("carrierId"),
                                carrier_name=q.get("carrierName"),
                                product_line_id=q.get("productLineId"),
                                product_name=q.get("productName"),
                                premium=q.get("premium"),
                                items=q.get("items"),
                                sold=1 if q.get("sold") else 0,
                                effective_date=q.get("effectiveDate"),
                                potential_revenue=q.get("potentialRevenue"),
                                property_address=q.get("propertyAddress"),
                                raw_json=q,
                                synced_at=sync_start,
                            ))
            except Exception as e:
                logger.warning(f"Failed to sync quotes for lead {lead.id}: {e}")

            # Parse and upsert opportunities from detail response
            async with async_session() as session:
                async with session.begin():
                    await session.execute(
                        delete(LeadOpportunity).where(LeadOpportunity.lead_id == lead.id)
                    )
                    for opp in (detail.get("opportunities") or []):
                        opp_id = opp.get("id")
                        if opp_id is None:
                            continue
                        await session.merge(LeadOpportunity(
                            id=opp_id,
                            lead_id=lead.id,
                            carrier_id=opp.get("carrierId"),
                            product_line_id=opp.get("productLineId"),
                            status=opp.get("status"),
                            premium=opp.get("premium"),
                            items=opp.get("items"),
                            property_address=opp.get("propertyAddress"),
                            raw_json=opp,
                            synced_at=sync_start,
                        ))

            # Fetch files separately (not included in detail endpoint)
            try:
                files = await fetch_lead_files(jwt, lead.id, file_type=1)
                async with async_session() as session:
                    async with session.begin():
                        await session.execute(
                            delete(LeadFile).where(LeadFile.lead_id == lead.id)
                        )
                        for f in files:
                            f_id = f.get("id")
                            if f_id is None:
                                continue
                            await session.merge(LeadFile(
                                id=f_id,
                                lead_id=lead.id,
                                title=f.get("title"),
                                media_type=f.get("mediaType"),
                                file_type=f.get("fileType"),
                                size=f.get("size"),
                                create_date=f.get("createDate"),
                                comments=f.get("comments"),
                                raw_json=f,
                                synced_at=sync_start,
                            ))
            except Exception as e:
                logger.warning(f"Failed to sync files for lead {lead.id}: {e}")

            detail_success += 1
        except Exception as e:
            detail_errors += 1
            logger.warning(f"Failed to sync detail for lead {lead.id}: {e}")

    logger.info(f"Detail sync: {detail_success} succeeded, {detail_errors} failed")

    # Clear backfill flag if set
    if needs_detail_backfill:
        async with async_session() as session:
            async with session.begin():
                await session.merge(SyncMeta(
                    key="detail_backfill_needed",
                    value="false",
                    updated_at=sync_start,
                ))
        logger.info("Detail backfill complete — flag cleared")

    # Step 3: Delete stale leads only on full sync (delta only upserts recent changes)
    if not is_delta and synced_pipeline_ids:
        async with async_session() as session:
            async with session.begin():
                result = await session.execute(
                    delete(Lead).where(
                        Lead.synced_at < sync_start,
                        Lead.pipeline_id.in_(synced_pipeline_ids),
                    )
                )
                stale_count = result.rowcount
                if stale_count > 0:
                    logger.info(f"Removed {stale_count} stale leads from {len(synced_pipeline_ids)} synced pipelines")

    # Step 4: Sync employees
    await _rate_limit_delay()
    try:
        employees_data = await fetch_employees(jwt)
        logger.info(f"Fetched {len(employees_data)} employees from AgencyZoom")

        async with async_session() as session:
            async with session.begin():
                for emp in employees_data:
                    emp_id = emp.get("id")
                    if emp_id is None:
                        continue
                    await session.merge(Employee(
                        id=emp_id,
                        firstname=emp.get("firstname"),
                        lastname=emp.get("lastname"),
                        email=emp.get("email"),
                        phone=emp.get("phone"),
                        is_producer=1 if emp.get("isProducer") else 0,
                        is_active=1 if emp.get("isActive") else 0,
                        is_owner=1 if emp.get("isOwner") else 0,
                        user_id=emp.get("userId"),
                        synced_at=sync_start,
                    ))
    except Exception as e:
        logger.error(f"Failed to sync employees: {e}")

    # Record successful sync
    await _set_last_successful_sync(sync_start)
    logger.info(f"{sync_type.title()} sync complete: {len(pipelines_data)} pipelines, {total_leads} leads")
