# Pipeline Dashboard Statistics

## Summary

Add inline lead counts to filter items (producer dropdown, activity pills) and a summary stats bar above the kanban board showing Total Leads, Total Premium, and Avg Premium.

## Inline Counts on Filter Items

### Producer Dropdown
- Show lead count next to each producer name: "Chad Forrester (12)"
- Counts reflect currently displayed leads (respects all active filters except producer filter itself)

### Activity Pills
- Show lead count on each pill: "7d (23)" / "90d+ (12)"
- Counts are for all leads matching that time bucket (independent of which pill is selected)

## Summary Stats Bar

Horizontal bar between filter panel and kanban board, always visible. Three stat cards in a row:

| Total Leads | Total Premium | Avg Premium |
|------------|--------------|-------------|
| 47 | $142,300 | $3,028 |

- Updates dynamically when any filter changes
- Values computed from the leads currently returned by the board endpoint
- Premium formatted with commas and dollar sign, no decimals

## Backend

### Stats in Template Context
Both board endpoints (`/pipeline/api/board/all` and `/pipeline/api/board/{pipeline_id}`) compute and pass to template:
- `total_leads`: `len(all_leads)`
- `total_premium`: `sum(lead.premium for lead in all_leads if lead.premium)`
- `avg_premium`: `total_premium / total_leads` if total_leads > 0 else 0

### Filter Counts Endpoint
`GET /pipeline/api/filter-counts` returns JSON:
```json
{
  "producers": [{"firstname": "Chad", "lastname": "Forrester", "count": 12}, ...],
  "activity": {"1": 5, "3": 10, "7": 23, "14": 35, "30": 45, "90+": 12}
}
```

Accepts query params: `pipeline_id` (default "all"), `view`, `producers` — so counts respect current filter context (except the dimension being counted).

Activity counts use the same date logic as `_apply_filters`:
- Buckets 1/3/7/14/30: leads where `last_activity_date >= cutoff`
- Bucket 90+: leads where `last_activity_date <= 90-day cutoff`

Producer counts: group by `assign_to_firstname` across leads matching current pipeline + view + activity filters.

## Frontend

### Stats Bar
- New partial `partials/stats_bar.html` rendered inside the kanban response
- Included at the top of both `kanban.html` and `kanban_all.html`

### Filter Counts JS
- `loadFilterCounts()` called on page load and after each filter change
- Updates producer checkbox labels with counts
- Updates activity pill text with counts
- Fetches from `/pipeline/api/filter-counts` with current filter params

## Files to Modify

| File | Change |
|------|--------|
| `board.py` | Add stats to template context, add filter-counts endpoint |
| `kanban.html` | Include stats_bar partial at top |
| `kanban_all.html` | Include stats_bar partial at top |
| `board.html` | JS to fetch/render filter counts on pills and producer items |
| `style.css` | Stats bar and count badge styles |
| New: `partials/stats_bar.html` | Stats bar template |
