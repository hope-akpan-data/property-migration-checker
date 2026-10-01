# Hypothetical owner-approved corrections

These are deliberate synthetic example changes, not automatically inferred repairs.

| Dirty data | Corrected example | Assumed approval |
|---|---|---|
| Second P-002 row | Reassigned to P-004 | Owner confirms these are distinct properties and supplies the right ID |
| Blank postcode for P-003 | DEMO-03 | Owner supplies a fictional demo postcode |
| Leading/trailing spaces in P-004 address | Trimmed | Formatting change approved |
| T-002 references P-999 | References P-004 | Owner confirms the intended property |
| T-003 ends before it starts | End changed to 2027-01-01 | Owner confirms the end date |
| T-004 invalid start date | Changed to 2026-02-28 | Owner confirms the date |
| T-004 rent -900 | Changed to 900 | Owner confirms the amount, not an automatic absolute-value conversion |
| M-002 status In-Progress | in_progress | Destination status mapping approved |
| M-003 blank property ID | P-003 | Owner confirms the link |
| M-004 impossible opened date | 2026-02-28 | Owner confirms the date |

The corrected source has 5 properties, 4 tenancies and 4 maintenance records. The target fixture replaces P-005 with P-099 and changes T-001 rent from 1200 to 1250. These are deliberate import discrepancies, not approved corrections.
