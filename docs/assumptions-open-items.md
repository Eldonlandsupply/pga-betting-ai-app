# Assumptions, Open Items, Known Weak Points

## Assumptions
1. Repository currently lacks production code, so this change defines architecture contracts first.
2. A downstream runner will provide raw event/player/market payloads as JSON.
3. Market prices are decimal odds unless format metadata states otherwise.
4. Confidence scoring remains bounded [0, 1].

## Open Items
1. UNKNOWN: Authoritative data source priority list by tour.
2. UNKNOWN: Actual bookmaker feed schema and update cadence.
3. UNKNOWN: Existing model scoring code to integrate with these contracts.
4. UNKNOWN: Historical audit database location and retention policy.

## Known Weak Points
1. LIV and some DP World events may have sparse SG-like data.
2. Injury and WD signal quality can degrade quickly.
3. Travel burden modeling may be noisy without robust timezone itinerary data.
4. FRL markets have high variance and lower confidence reliability.

## What Changes if Assumptions Fail
- If odds are not decimal, implied probability conversion must be adapted.
- If no market timestamps exist, all edge confidence should be downgraded.
- If no source authority metadata is available, conflict handling becomes less trustworthy.
