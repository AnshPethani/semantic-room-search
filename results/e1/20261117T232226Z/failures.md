# E1 top-1 misses

Every command and method whose top-1 score is below 1 (a fractional score is a tie at the cut-off). For the report's failure analysis.

## gemini_full (6 of 39)

### e1_05 (explicit): find the teddy bear
- labeled: B1, B2
- ranked: LR 0.350 > B1 0.280 > B2 0.270 > D 0.050 > K 0.030 > E 0.020
- top-1 score: 0.00
- rationale: Teddy bears are toys typically found in bedrooms or the living room.

### e1_16 (category): find some tableware
- labeled: D
- ranked: K 0.600 > LR 0.200 > D 0.100 > E 0.050 > B1 0.025 > B2 0.025
- top-1 score: 0.00
- rationale: Tableware such as cups, bowls, and bottles are primarily kept and used in the kitchen and dining area, or sometimes the living room.

### e1_24 (need): I need to get some work done
- labeled: B1, B2
- ranked: LR 0.400 > B1 0.200 > B2 0.150 > K 0.100 > D 0.100 > E 0.050
- top-1 score: 0.00
- rationale: Working typically involves a laptop, book, or cell phone, which are commonly found in living rooms and bedrooms.

### e1_26 (need): my child wants something to cuddle
- labeled: B1, B2
- ranked: LR 0.300 > B1 0.300 > B2 0.250 > E 0.050 > K 0.050 > D 0.050
- top-1 score: 0.50
- rationale: Something to cuddle usually implies a teddy bear, which is most likely found in bedrooms or the living room.

### e1_28 (relational): check the room next to the kitchen for a cup
- labeled: LR
- ranked: E 0.450 > LR 0.450 > D 0.030 > B1 0.030 > K 0.020 > B2 0.020
- top-1 score: 0.50
- rationale: The kitchen has doors connecting directly to the entry hall and the living room.

### e1_30 (relational): find the remote in a room connected to the entry hall
- labeled: LR
- ranked: K 0.450 > LR 0.450 > D 0.030 > B2 0.030 > E 0.020 > B1 0.020
- top-1 score: 0.50
- rationale: The entry hall is connected by a door to the kitchen and the living room.

## gemini_names_only (9 of 39)

### e1_05 (explicit): find the teddy bear
- labeled: B1, B2
- ranked: LR 0.350 > B1 0.250 > B2 0.250 > E 0.050 > K 0.050 > D 0.050
- top-1 score: 0.00
- rationale: Teddy bears are usually found in bedrooms or living rooms.

### e1_16 (category): find some tableware
- labeled: D
- ranked: K 0.650 > D 0.180 > LR 0.100 > E 0.030 > B1 0.020 > B2 0.020
- top-1 score: 0.00
- rationale: Tableware such as cups and bowls are predominantly found in the kitchen and dining area.

### e1_24 (need): I need to get some work done
- labeled: B1, B2
- ranked: LR 0.350 > B1 0.200 > D 0.150 > B2 0.150 > K 0.100 > E 0.050
- top-1 score: 0.00
- rationale: Working typically involves a laptop, books, or phone, which are usually found in living rooms, bedrooms, or dining areas.

### e1_26 (need): my child wants something to cuddle
- labeled: B1, B2
- ranked: LR 0.300 > B1 0.300 > B2 0.250 > E 0.050 > K 0.050 > D 0.050
- top-1 score: 0.50
- rationale: Children usually keep cuddling items like teddy bears in their bedrooms or the living room.

### e1_28 (relational): check the room next to the kitchen for a cup
- labeled: LR
- ranked: E 0.450 > LR 0.450 > K 0.050 > B1 0.020 > B2 0.020 > D 0.010
- top-1 score: 0.50
- rationale: The kitchen has doors connecting to the entry hall and the living room, so those are the rooms next to the kitchen.

### e1_30 (relational): find the remote in a room connected to the entry hall
- labeled: LR
- ranked: K 0.450 > LR 0.450 > E 0.050 > B1 0.020 > B2 0.020 > D 0.010
- top-1 score: 0.50
- rationale: Remotes are typically in the kitchen or living room, which are the rooms connected to the entry hall.

### e1_31 (relational): find a banana in the room next to the dining area
- labeled: LR
- ranked: E 0.450 > K 0.450 > LR 0.040 > D 0.020 > B1 0.020 > B2 0.020
- top-1 score: 0.00
- rationale: The rooms directly connected to the dining area are the entry hall and the kitchen.
- constraint: expected LR; got E, K

### e1_33 (relational): find something to eat in the room next to the entry hall
- labeled: K
- ranked: LR 0.850 > E 0.050 > K 0.050 > D 0.020 > B1 0.020 > B2 0.010
- top-1 score: 0.00
- rationale: The living room is next to the entry hall and is the room constrained by the command for food items.
- constraint: expected K, LR; got LR

### e1_36 (relational): look in the room next to bedroom 2 for a cup
- labeled: LR
- ranked: E 0.850 > K 0.050 > LR 0.040 > D 0.030 > B1 0.020 > B2 0.010
- top-1 score: 0.00
- rationale: Bedroom 2 is connected only to the entry hall, which is therefore the room next to it.
- constraint: expected LR; got E
