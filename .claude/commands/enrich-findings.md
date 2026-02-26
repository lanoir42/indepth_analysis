---
name: enrich-findings
description: Enrich euro macro findings JSON with WebSearch results
---

# Enrich Euro Macro Findings with Web Search

Given the findings JSON at: $ARGUMENTS

## Instructions

1. Read the JSON file at the path above.
2. Extract `year` and `month` from the `meta` object.
3. Run **18 WebSearch queries** across 3 categories (6 queries each). Use the year and month to make queries time-specific.

### Media queries (6)
Search for Korean and English media coverage of the European economy:
1. `"유럽 경제 전망 {year}년 {month}월"` (Korean European economy outlook)
2. `"유로존 경기 동향 {year}년 {month}월"` (Eurozone business trends)
3. `"eurozone economy {year} {month_name}"` (English eurozone economy)
4. `"european recession risk {year}"` (recession risk)
5. `"유럽 금융시장 위기 {year}"` (European financial market crisis)
6. `"euro area economic outlook {month_name} {year}"` (Euro area outlook)

### Institutional queries (6)
Search for official ECB, IMF, BIS, OECD sources:
1. `"ECB monetary policy decision {year}"` (ECB decisions)
2. `"ECB interest rate {month_name} {year}"` (ECB rate decisions)
3. `"IMF European economic outlook {year}"` (IMF outlook)
4. `"OECD eurozone forecast {year}"` (OECD forecast)
5. `"BIS European banking {year}"` (BIS banking)
6. `"European Commission economic forecast {year}"` (EC forecast)

### Data queries (6)
Search for key eurozone economic indicators:
1. `"eurozone PMI {month_name} {year}"` (PMI data)
2. `"eurozone CPI inflation {month_name} {year}"` (inflation data)
3. `"eurozone GDP growth {year} Q{quarter}"` (GDP growth, compute quarter from month)
4. `"eurozone unemployment rate {year}"` (unemployment)
5. `"유로존 소비자물가 {year}년 {month}월"` (Korean CPI)
6. `"유로존 제조업 PMI {year}년 {month}월"` (Korean PMI)

Where `{month_name}` is the English month name (e.g., "February") and `{quarter}` is computed as `(month - 1) // 3 + 1`.

4. For each category, create an `AgentResult` entry:
   - `agent_name`: `"WebSearch-Media"`, `"WebSearch-Institutional"`, or `"WebSearch-Data"`
   - `findings`: list of `ResearchFinding` objects from search results
   - `search_queries`: the 6 queries used

   For each search result, create a finding with:
   - `title`: the result title
   - `summary`: the result snippet/description
   - `source_url`: the result URL
   - `source_name`: extract domain from URL (e.g., "ecb.europa.eu")
   - `published_date`: if available from search results, otherwise null
   - `relevance_score`: 0.5 (default for web search)
   - `category`: the category name ("미디어", "기관보고서", or "경제지표")

5. **Deduplicate** findings by URL across all agent results (existing + new). Keep the first occurrence.

6. Append the 3 new `AgentResult` entries to the existing `agent_results` array in the JSON.

7. Update `meta.generated_at` to the current timestamp.

8. Write the enriched JSON back to the same file path.

9. Print a summary: how many new findings were added per category and the total count.

## Output format

The enriched JSON should maintain the same structure:
```json
{
  "meta": {"year": ..., "month": ..., "generated_at": "...", "pipeline_version": "2.0"},
  "agent_results": [
    {"agent_name": "KCIF", "findings": [...], ...},
    {"agent_name": "WebSearch-Media", "findings": [...], ...},
    {"agent_name": "WebSearch-Institutional", "findings": [...], ...},
    {"agent_name": "WebSearch-Data", "findings": [...], ...}
  ]
}
```
