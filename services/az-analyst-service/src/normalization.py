"""Pipeline and lead source classification for executive reporting.

Maps AgencyZoom pipeline names and lead source names to standardized
categories for funnel analysis. Unknown values fall through to "other".
"""

# Pipeline name -> channel_type
# Describes how leads enter the agency
PIPELINE_CHANNEL_MAP = {
    "0 Win-Back to Farmers": "reactivation",
    "1 NPL Call/Walk In": "inbound",
    "1 NPL Distressed Zip Code": "outbound",
    "1 NPL FFQ": "internet",
    "1 NPL Internet": "internet",
    "1 NPL Resurrected": "reactivation",
    "2 Cross-Sell": "internal",
    "2 ReShop/ReWrite": "internal",
    "3 Life Pipeline": "internal",
    "4 New Comm. Leads": "mixed",
    "5 Incoming AOR Transfers": "transfer",
    "Commercial Leads Not Quoted": "commercial",
    "Lender Relationship Pipeline": "partner",
    "Personal QNC": "internal",
    "Personal Leads Not Quoted/Aged": "internal",
    "Training Pipeline - New Personal Leads": "training",
}

# Pipeline name -> intent_type
# Describes lead quality / buying intent
PIPELINE_INTENT_MAP = {
    "0 Win-Back to Farmers": "existing_customer",
    "1 NPL Call/Walk In": "high_intent",
    "1 NPL Distressed Zip Code": "targeted",
    "1 NPL FFQ": "cold_purchased",
    "1 NPL Internet": "cold_purchased",
    "1 NPL Resurrected": "warm",
    "2 Cross-Sell": "existing_customer",
    "2 ReShop/ReWrite": "existing_customer",
    "3 Life Pipeline": "cross_sell",
    "4 New Comm. Leads": "commercial",
    "5 Incoming AOR Transfers": "high_intent",
    "Commercial Leads Not Quoted": "commercial",
    "Lender Relationship Pipeline": "partner_referral",
    "Personal QNC": "quality_check",
    "Personal Leads Not Quoted/Aged": "stale",
    "Training Pipeline - New Personal Leads": "training",
}

# Lead source name -> source_group
# Groups similar lead sources for reporting
SOURCE_GROUP_MAP = {
    "EverQuote": "vendor_lead",
    "FFQ": "vendor_lead",
    "QuoteWizard": "vendor_lead",
    "MediaAlpha": "vendor_lead",
    "BOB": "book",
    "Reshop/Rewrite": "book",
    "Cross-Sale": "book",
    "Rec. Engine - Cross-Sell": "book",
    "Rec Engine - QNC": "book",
    "Call-In": "inbound",
    "Walk-In": "inbound",
    "Realtor": "referral",
    "Customer Referral": "referral",
    "a satisfied client": "referral",
    "Todd Huebler with State Farm": "referral",
    "Distressed Zip Code": "targeted",
    "Lender Partners": "partner",
}


def classify_pipeline(workflow_name: str | None) -> dict:
    """Return channel_type and intent_type for a pipeline name."""
    name = workflow_name or ""
    return {
        "channel_type": PIPELINE_CHANNEL_MAP.get(name, "other"),
        "intent_type": PIPELINE_INTENT_MAP.get(name, "other"),
    }


# Pipelines where the lead initiated contact (already contacted on creation)
# contact_date should equal create_date for these pipelines
AUTO_CONTACT_PIPELINES = {
    "1 NPL Call/Walk In",
    "5 Incoming AOR Transfers",
}


def classify_source(lead_source_name: str | None) -> str:
    """Return source_group for a lead source name."""
    return SOURCE_GROUP_MAP.get(lead_source_name or "", "other")


def is_auto_contact_pipeline(workflow_name: str | None) -> bool:
    """Return True if leads in this pipeline are contacted by definition (they called/walked in)."""
    return (workflow_name or "") in AUTO_CONTACT_PIPELINES


# Compliance thresholds by intent_type
# quote_rate thresholds: passing >= high, warning >= low, failing < low
COMPLIANCE_THRESHOLDS = {
    "high_intent": {"passing": 0.90, "warning": 0.70},
    "existing_customer": {"passing": 0.80, "warning": 0.60},
    "cold_purchased": {"passing": 0.50, "warning": 0.30},
    "targeted": {"passing": 0.40, "warning": 0.20},
    "warm": {"passing": 0.60, "warning": 0.40},
    "other": {"passing": 0.50, "warning": 0.30},
}


def get_compliance_status(quote_rate: float, intent_type: str) -> str:
    """Determine compliance status based on quote rate and pipeline intent."""
    thresholds = COMPLIANCE_THRESHOLDS.get(intent_type, COMPLIANCE_THRESHOLDS["other"])
    if quote_rate >= thresholds["passing"]:
        return "passing"
    elif quote_rate >= thresholds["warning"]:
        return "warning"
    return "failing"
