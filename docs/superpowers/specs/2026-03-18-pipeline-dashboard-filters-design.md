# Pipeline Dashboard Filters

## Summary

Add a collapsible filter panel to the pipeline dashboard with Producer multi-select and Last Activity date filters. Also add `lastActivityDate` from AgencyZoom to replace `enterStageDate` on lead cards.

## Layout

Collapsible filter panel toggled by a "Filters" button in the nav bar. The button shows an active filter count badge when filters are applied. The panel sits between the nav bar and the kanban board.

### Filter Panel Contents

Three sections separated by vertical dividers:

1. **Producer** (multi-select checkbox dropdown)
2. **Last Activity** (single-select pill buttons)
3. **View** (My Leads / All Leads toggle — relocated from nav bar)

## Producer Filter

### UI
- Dropdown trigger shows selected names ("Chad F., Jessica W.") or "All Producers" when no filter
- Clicking opens a checkbox list of all producers
- Select All / Clear links at the bottom
- Populated dynamically from distinct producer names in the leads table

### Backend
- New endpoint: `GET /pipeline/api/producers` returns distinct `assign_to_firstname`, `assign_to_lastname` pairs from `pd_leads`
- Query param: `producers=Chad,Jessica` (comma-separated first names)
- Filter: `Lead.assign_to_firstname.in_(producer_list)`

## Last Activity Filter

### UI
- Single-select pill buttons: Any, 1d, 3d, 7d, 14d, 30d, 90d
- "Any" = no time filter (default)
- Selected pill highlighted in purple

### Backend
- Query param: `activity_days=7`
- Filter: `Lead.last_activity_date >= (today - N days)` as ISO string comparison
- No filter applied when `activity_days` is absent or "any"

## Data Changes

### New Column
Add `last_activity_date` to `pd_leads` table:
```python
last_activity_date = Column(String(50), nullable=True)
```

### Sync Update
In `sync.py`, add to lead merge:
```python
last_activity_date=lead.get("lastActivityDate"),
```

### Lead Card Update
In `lead_card.html`, display `last_activity_date` instead of `enter_stage_date`.

## API Changes

### Existing Endpoints Modified
Both `/pipeline/api/board/all` and `/pipeline/api/board/{pipeline_id}` accept new query params:
- `view` (existing): "all" or "my"
- `producers` (new): comma-separated first names, empty = all
- `activity_days` (new): integer days, absent = no filter

### New Endpoint
`GET /pipeline/api/producers` — returns JSON list of `{firstname, lastname}` objects from distinct values in `pd_leads`.

## Frontend Changes

### Nav Bar
- Remove My Leads / All Leads toggle from nav center
- Add Filters button to nav right area (before user name)
- Badge shows count of active filters (producer selections + activity != "any")
- Border color changes to purple when filters active

### Filter Panel
- Hidden by default, slides open on Filters button click
- Contains Producer dropdown, Last Activity pills, and View toggle
- Closing the panel does not clear filters

### JavaScript
- `filterState` object tracks: `producers[]`, `activityDays`, `leadView`, `panelOpen`
- `loadBoard()` constructs URL from all filter state
- Each filter change triggers `loadBoard()` via HTMX
- Producer dropdown: custom JS for checkbox behavior (click doesn't close dropdown)

## Filter Button States

| State | Appearance |
|-------|-----------|
| No filters active | Gray button, no badge |
| Filters active | Purple border, badge with count |

## Files to Modify

| File | Change |
|------|--------|
| `database.py` | Add `last_activity_date` column |
| `sync.py` | Sync `lastActivityDate` from AZ |
| `board.py` | Add query params, producers endpoint, filter logic |
| `board.html` | Replace view toggle with Filters button, add panel HTML |
| `lead_card.html` | Show `last_activity_date` instead of `enter_stage_date` |
| `style.css` | Filter panel, dropdown, pill, badge styles |
