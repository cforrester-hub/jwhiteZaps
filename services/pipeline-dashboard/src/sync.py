"""Background data sync from AgencyZoom to local PostgreSQL cache."""

import logging
from datetime import datetime

from sqlalchemy import delete, text

from .az_client import (
    _rate_limit_delay,
    fetch_all_leads_for_pipeline,
    fetch_employees,
    fetch_pipelines_and_stages,
    system_login,
)
from .database import Employee, Lead, Pipeline, Stage, async_session

logger = logging.getLogger(__name__)


async def sync_all():
    """Main sync job: fetch pipelines, stages, and leads from AgencyZoom."""
    sync_start = datetime.utcnow()
    logger.info("Starting pipeline data sync")

    try:
        jwt = await system_login()
    except Exception as e:
        logger.error(f"Sync failed: could not authenticate - {e}")
        return

    # Step 1: Sync pipelines and stages
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

    # Step 2: Sync leads per pipeline
    total_leads = 0
    synced_pipeline_ids = []  # Track successful syncs for safe stale deletion
    for p in pipelines_data:
        pid = p.get("id")
        if pid is None:
            continue

        try:
            # Convert to int for the API call (workflowId expects integer)
            pipeline_int_id = int(pid)
            leads = await fetch_all_leads_for_pipeline(jwt, pipeline_int_id)
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

                    await session.merge(Lead(
                        id=lead_id,
                        pipeline_id=str(pid),
                        stage_id=str(lead.get("workflowStageId", "")),
                        assigned_to=lead.get("assignedTo"),
                        firstname=lead.get("firstname"),
                        lastname=lead.get("lastname"),
                        lead_type=lead.get("leadType"),
                        phone=lead.get("phone"),
                        email=lead.get("email"),
                        status=lead.get("status"),
                        premium=lead.get("premium"),
                        quoted=lead.get("quoted"),
                        enter_stage_date=lead.get("enterStageDate"),
                        last_activity_date=lead.get("lastActivityDate"),
                        contact_date=lead.get("contactDate"),
                        lead_source_name=lead.get("leadSourceName"),
                        workflow_name=lead.get("workflowName"),
                        workflow_stage_name=lead.get("workflowStageName"),
                        assign_to_firstname=lead.get("assignToFirstname"),
                        assign_to_lastname=lead.get("assignToLastname"),
                        raw_json=lead,
                        synced_at=sync_start,
                    ))

                total_leads += len(leads)

        await _rate_limit_delay()

    # Step 3: Delete stale leads only from successfully synced pipelines
    if synced_pipeline_ids:
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

    logger.info(f"Sync complete: {len(pipelines_data)} pipelines, {total_leads} leads")
