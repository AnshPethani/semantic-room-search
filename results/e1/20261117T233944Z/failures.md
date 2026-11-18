# E1 top-1 misses

Every command and method whose top-1 score is below 1 (a fractional score is a tie at the cut-off). For the report's failure analysis.

## keyword (12 of 39)

### e1_16 (category): find some tableware
- labeled: D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Keyword fallback: no keyword matched; uniform prior over all rooms.

### e1_22 (need): I need to make a call
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Keyword fallback: no keyword matched; uniform prior over all rooms.

### e1_23 (need): I want to watch TV
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Keyword fallback: no keyword matched; uniform prior over all rooms.

### e1_24 (need): I need to get some work done
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Keyword fallback: no keyword matched; uniform prior over all rooms.

### e1_26 (need): my child wants something to cuddle
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Keyword fallback: no keyword matched; uniform prior over all rooms.

### e1_27 (need): I need to check my email
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Keyword fallback: no keyword matched; uniform prior over all rooms.

### e1_28 (relational): check the room next to the kitchen for a cup
- labeled: LR
- ranked: K 0.450 > D 0.300 > LR 0.100 > E 0.050 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Keyword fallback matched: cup.

### e1_29 (relational): look in the bedroom next to the living room for a book
- labeled: B1, B2
- ranked: LR 0.300 > B1 0.300 > B2 0.300 > E 0.040 > K 0.030 > D 0.030
- top-1 score: 0.67
- rationale: Keyword fallback matched: book.

### e1_31 (relational): find a banana in the room next to the dining area
- labeled: LR
- ranked: K 0.450 > D 0.300 > LR 0.100 > E 0.050 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Keyword fallback matched: banana.

### e1_32 (relational): look for the laptop in a bedroom
- labeled: B1, B2
- ranked: LR 0.300 > B1 0.250 > B2 0.250 > D 0.100 > E 0.050 > K 0.050
- top-1 score: 0.00
- rationale: Keyword fallback matched: laptop.

### e1_35 (relational): find the teddy bear in the room connected to the kitchen and both bedrooms
- labeled: LR
- ranked: B1 0.400 > B2 0.400 > LR 0.100 > E 0.040 > K 0.030 > D 0.030
- top-1 score: 0.00
- rationale: Keyword fallback matched: teddy bear.

### e1_36 (relational): look in the room next to bedroom 2 for a cup
- labeled: LR
- ranked: K 0.450 > D 0.300 > LR 0.100 > E 0.050 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Keyword fallback matched: cup.

## uniform (39 of 39)

### e1_01 (explicit): find the banana
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_02 (explicit): find the remote
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_03 (explicit): where is the laptop
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_04 (explicit): find my cup
- labeled: K, D, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.67
- rationale: Uniform prior over all rooms.

### e1_05 (explicit): find the teddy bear
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_06 (explicit): find the book
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_07 (explicit): find the bottle
- labeled: K, LR, D, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.83
- rationale: Uniform prior over all rooms.

### e1_08 (explicit): locate the cell phone
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_09 (explicit): find the orange
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_10 (category): find me food
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_11 (category): find a piece of fruit
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_12 (category): find something to drink from
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_13 (category): find some electronics
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_14 (category): find a toy
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_15 (category): find something to read
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_16 (category): find some tableware
- labeled: D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_17 (category): find a beverage container
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_18 (category): find a device with a screen
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_19 (need): I'm thirsty
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_20 (need): I'm hungry
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_21 (need): I want to read
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_22 (need): I need to make a call
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_23 (need): I want to watch TV
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_24 (need): I need to get some work done
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_25 (need): I want a snack
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_26 (need): my child wants something to cuddle
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_27 (need): I need to check my email
- labeled: LR, B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.50
- rationale: Uniform prior over all rooms.

### e1_28 (relational): check the room next to the kitchen for a cup
- labeled: LR
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_29 (relational): look in the bedroom next to the living room for a book
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_30 (relational): find the remote in a room connected to the entry hall
- labeled: LR
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_31 (relational): find a banana in the room next to the dining area
- labeled: LR
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_32 (relational): look for the laptop in a bedroom
- labeled: B1, B2
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_33 (relational): find something to eat in the room next to the entry hall
- labeled: K
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_34 (relational): check the kitchen for a bottle
- labeled: K
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_35 (relational): find the teddy bear in the room connected to the kitchen and both bedrooms
- labeled: LR
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_36 (relational): look in the room next to bedroom 2 for a cup
- labeled: LR
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.17
- rationale: Uniform prior over all rooms.

### e1_37 (explicit): find the apple
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_38 (explicit): where did I leave the sandwich
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

### e1_39 (explicit): locate the bowl
- labeled: K, D
- ranked: E 0.167 > K 0.167 > LR 0.167 > D 0.167 > B1 0.167 > B2 0.167
- top-1 score: 0.33
- rationale: Uniform prior over all rooms.

## ollama_full (32 of 39)

### e1_01 (explicit): find the banana
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Bananas are often kept in the kitchen or entry hall, but can also be in the living room or dining area.

### e1_04 (explicit): find my cup
- labeled: K, D, B1, B2
- ranked: E 0.412 > K 0.309 > LR 0.206 > D 0.052 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: Cups are often used in the kitchen or entry hall, but can also be found in the living room.

### e1_05 (explicit): find the teddy bear
- labeled: B1, B2
- ranked: E 0.200 > B1 0.200 > B2 0.200 > K 0.150 > LR 0.150 > D 0.100
- top-1 score: 0.67
- rationale: Teddy bears are often kept in bedrooms or living areas, but can also be found in entry halls or kitchens.

### e1_06 (explicit): find the book
- labeled: LR, B1, B2
- ranked: E 0.200 > B1 0.200 > B2 0.200 > K 0.150 > LR 0.150 > D 0.100
- top-1 score: 0.67
- rationale: Books can be found in various rooms, so a uniform distribution is a reasonable guess.

### e1_07 (explicit): find the bottle
- labeled: K, LR, D, B1, B2
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Bottles are often found in entry halls, kitchens, and living rooms, but can be anywhere.

### e1_08 (explicit): locate the cell phone
- labeled: LR, B1, B2
- ranked: E 0.400 > K 0.250 > LR 0.200 > D 0.050 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Cell phones are often kept in entry halls or kitchens, but can be found in other rooms as well.

### e1_09 (explicit): find the orange
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Oranges are usually kept in the kitchen or entry hall, but can also be in the living room or dining area.

### e1_10 (category): find me food
- labeled: K, D
- ranked: E 0.263 > K 0.263 > LR 0.263 > D 0.105 > B1 0.053 > B2 0.053
- top-1 score: 0.33
- rationale: Food is usually found in the kitchen or dining area, but can also be in the entry hall or living room.

### e1_11 (category): find a piece of fruit
- labeled: K, D
- ranked: E 0.250 > K 0.250 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.050
- top-1 score: 0.50
- rationale: Fruits are commonly found in the kitchen or entry hall, but can also be in the living room or dining area.

### e1_12 (category): find something to drink from
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: People usually drink from bottles or cups in the entry hall, kitchen, or living room.

### e1_14 (category): find a toy
- labeled: LR, B1, B2
- ranked: E 0.200 > B1 0.200 > B2 0.200 > K 0.150 > LR 0.150 > D 0.100
- top-1 score: 0.67
- rationale: Toys are often found in living areas or entry halls, but also in bedrooms.

### e1_16 (category): find some tableware
- labeled: D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Tableware is often found in the entry hall, kitchen, and dining area, but can also be in the living room.

### e1_17 (category): find a beverage container
- labeled: K, D
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Beverage containers are commonly found in kitchens and entry halls, but also in dining and living areas.

### e1_19 (need): I'm thirsty
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Thirst is usually quenched with a drink, so bottles, cups, and bowls are plausible, mostly in entry hall and kitchen.

### e1_20 (need): I'm hungry
- labeled: K, D
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Hunger suggests looking for food, which is often found in the kitchen or entry hall, but also in the dining area or living room.

### e1_21 (need): I want to read
- labeled: LR, B1, B2
- ranked: E 0.200 > B1 0.200 > B2 0.200 > K 0.150 > LR 0.150 > D 0.100
- top-1 score: 0.67
- rationale: Reading can happen in various rooms, but a book is more likely to be found in a living or sleeping area.

### e1_22 (need): I need to make a call
- labeled: LR, B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Cell phones and laptops are usually found in areas where people spend time, such as the entry hall, kitchen, or living room.

### e1_23 (need): I want to watch TV
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: TV watching is most likely in the living room, but a remote could be in the entry hall, kitchen, or dining area, and a laptop or cell phone could be anywhere.

### e1_24 (need): I need to get some work done
- labeled: B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Work is often done at a desk, which is likely to be in the entry hall or kitchen, but also possible in the living room or dining area.

### e1_25 (need): I want a snack
- labeled: K, D
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: A snack is a common request, so several food and drink items are plausible, mostly in the entry hall, kitchen, and living room.

### e1_26 (need): my child wants something to cuddle
- labeled: B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Children often cuddle with toys in the entry hall or living room, but it's also possible in other rooms.

### e1_27 (need): I need to check my email
- labeled: LR, B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Email is usually checked on a laptop or cell phone, which are often found in entry hall, kitchen, or living room.

### e1_28 (relational): check the room next to the kitchen for a cup
- labeled: LR
- ranked: E 0.714 > K 0.204 > LR 0.051 > D 0.010 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: The room next to the kitchen is the entry hall, so most probability goes there.
- constraint: expected E, LR; got E

### e1_29 (relational): look in the bedroom next to the living room for a book
- labeled: B1, B2
- no LLM answer: invalid_output after 1 pass(es); counted as a miss

### e1_30 (relational): find the remote in a room connected to the entry hall
- labeled: LR
- ranked: E 0.693 > K 0.149 > LR 0.099 > D 0.030 > B1 0.020 > B2 0.010
- top-1 score: 0.00
- rationale: The entry hall has doors to the kitchen and living room, so those rooms are most likely to have the remote.
- constraint: expected K, LR; got E, K, LR

### e1_31 (relational): find a banana in the room next to the dining area
- labeled: LR
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: The dining area is in the living room, so the room next to the dining area is the living room.

### e1_32 (relational): look for the laptop in a bedroom
- labeled: B1, B2
- no LLM answer: invalid_output after 1 pass(es); counted as a miss

### e1_33 (relational): find something to eat in the room next to the entry hall
- labeled: K
- ranked: E 0.891 > K 0.050 > LR 0.030 > D 0.010 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: The room next to the entry hall is the kitchen, so most probability goes there, and several food-related objects are plausible.
- constraint: expected K, LR; got K

### e1_36 (relational): look in the room next to bedroom 2 for a cup
- labeled: LR
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: The room next to bedroom 2 is the living room, so most probability goes there.

### e1_37 (explicit): find the apple
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Apples are often eaten in the entry hall or kitchen, but can also be in the living room or dining area.

### e1_38 (explicit): where did I leave the sandwich
- labeled: K, D
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Sandwiches are often eaten in the entry hall or kitchen, but can also be in the living room.

### e1_39 (explicit): locate the bowl
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Bowl is often used in the kitchen or entry hall, but can also be in the living room or dining area.

## ollama_names_only (38 of 39)

### e1_01 (explicit): find the banana
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Bananas are often kept in the kitchen or entry hall, but can also be in other rooms.

### e1_02 (explicit): find the remote
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Remotes are often kept in entry halls or living rooms, but can also be in kitchens or dining areas.

### e1_03 (explicit): where is the laptop
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Laptops are often used in entry halls or kitchens, but can also be found in living rooms or bedrooms.

### e1_04 (explicit): find my cup
- labeled: K, D, B1, B2
- ranked: E 0.412 > K 0.309 > LR 0.206 > D 0.052 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: Cups are often used in the entry hall or kitchen, but can also be in the living room or dining area.

### e1_05 (explicit): find the teddy bear
- labeled: B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Teddy bears are often kept in entry halls or living rooms, but can also be in other rooms.

### e1_06 (explicit): find the book
- labeled: LR, B1, B2
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Books can be found in various rooms, so a general probability distribution is used.

### e1_07 (explicit): find the bottle
- labeled: K, LR, D, B1, B2
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Bottles are commonly found in entry halls, kitchens, and living rooms.

### e1_08 (explicit): locate the cell phone
- labeled: LR, B1, B2
- ranked: E 0.400 > K 0.250 > LR 0.200 > D 0.050 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Cell phones are often kept in entry halls or kitchens, but can be found in other rooms as well.

### e1_09 (explicit): find the orange
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Oranges are often kept in the entry hall or kitchen, but can also be in other rooms.

### e1_10 (category): find me food
- labeled: K, D
- no LLM answer: invalid_output after 1 pass(es); counted as a miss

### e1_11 (category): find a piece of fruit
- labeled: K, D
- ranked: E 0.250 > K 0.250 > LR 0.200 > D 0.150 > B2 0.100 > B1 0.050
- top-1 score: 0.50
- rationale: Fruits are commonly found in entry hall, kitchen, and living room.

### e1_12 (category): find something to drink from
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: People often drink from cups or bottles in various rooms, but the entry hall and kitchen are the most likely places.

### e1_13 (category): find some electronics
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Electronics are often found in entry halls, kitchens, and living rooms.

### e1_14 (category): find a toy
- labeled: LR, B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Toys are often found in entry halls or living rooms, but can also be in other rooms.

### e1_15 (category): find something to read
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: People often read in entry halls or kitchens, but also in living rooms and dining areas.

### e1_16 (category): find some tableware
- labeled: D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Tableware is often found in entry halls, kitchens, and dining areas.

### e1_17 (category): find a beverage container
- labeled: K, D
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Beverage containers are commonly found in entry hall, kitchen, and living room.

### e1_18 (category): find a device with a screen
- labeled: LR, B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Devices with screens are often used in entry halls, kitchens, and living rooms.

### e1_19 (need): I'm thirsty
- labeled: K, D
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Thirst is usually quenched with a drink, so bottles and cups are plausible, mostly in entry hall and kitchen.

### e1_20 (need): I'm hungry
- labeled: K, D
- ranked: E 0.250 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.100
- top-1 score: 0.00
- rationale: Hunger suggests food, so several food-related items are plausible, mostly in the entry hall and kitchen.

### e1_21 (need): I want to read
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.200 > LR 0.200 > D 0.150 > B1 0.100 > B2 0.050
- top-1 score: 0.00
- rationale: Reading is a common activity in entry halls and living rooms, but can also occur in other rooms.

### e1_22 (need): I need to make a call
- labeled: LR, B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Cell phones and laptops are usually found in the entry hall or kitchen, but laptops can also be in the living room.

### e1_23 (need): I want to watch TV
- labeled: LR, B1, B2
- ranked: E 0.300 > K 0.250 > LR 0.200 > D 0.150 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: TV watching is most likely in the entry hall or kitchen, but laptops and cell phones can also be used for streaming.

### e1_24 (need): I need to get some work done
- labeled: B1, B2
- ranked: E 0.400 > K 0.250 > LR 0.200 > D 0.050 > B1 0.050 > B2 0.050
- top-1 score: 0.00
- rationale: Work implies a laptop, but a book is also a plausible tool for productivity, so both are included, mostly likely in the entry hall or kitchen.

### e1_25 (need): I want a snack
- labeled: K, D
- ranked: E 0.211 > K 0.211 > LR 0.211 > D 0.158 > B1 0.105 > B2 0.105
- top-1 score: 0.33
- rationale: A snack can be anything, so several common snack items are plausible, mostly in the entry hall, kitchen, and living room.

### e1_26 (need): my child wants something to cuddle
- labeled: B1, B2
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: Children often cuddle with toys in the entry hall or living room, but it's also possible in other rooms.

### e1_27 (need): I need to check my email
- labeled: LR, B1, B2
- ranked: E 0.612 > K 0.204 > LR 0.102 > D 0.051 > B1 0.020 > B2 0.010
- top-1 score: 0.00
- rationale: Checking email is usually done on a laptop or cell phone, and these items are most likely to be found in the entry hall or kitchen.

### e1_28 (relational): check the room next to the kitchen for a cup
- labeled: LR
- ranked: E 0.800 > K 0.100 > LR 0.050 > D 0.030 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: The room next to the kitchen is the entry hall, so most probability goes there.
- constraint: expected E, LR; got K

### e1_29 (relational): look in the bedroom next to the living room for a book
- labeled: B1, B2
- no LLM answer: invalid_output after 1 pass(es); counted as a miss

### e1_30 (relational): find the remote in a room connected to the entry hall
- labeled: LR
- ranked: E 0.686 > K 0.147 > LR 0.098 > D 0.049 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: The entry hall is likely to be connected to the kitchen, but also possibly to the living room or dining area, so these rooms also have some probability.
- constraint: expected K, LR; got E

### e1_31 (relational): find a banana in the room next to the dining area
- labeled: LR
- ranked: E 0.612 > K 0.204 > LR 0.102 > D 0.051 > B1 0.020 > B2 0.010
- top-1 score: 0.00
- rationale: The dining area is in the dining area, and the only room adjacent to it is the entry hall.
- constraint: expected LR; got E

### e1_32 (relational): look for the laptop in a bedroom
- labeled: B1, B2
- no LLM answer: invalid_output after 1 pass(es); counted as a miss

### e1_33 (relational): find something to eat in the room next to the entry hall
- labeled: K
- ranked: E 0.891 > K 0.050 > LR 0.030 > D 0.010 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: The room next to the entry hall is the kitchen, so most probability goes there, but other food items could be in the entry hall or nearby rooms.
- constraint: expected K, LR; got E

### e1_35 (relational): find the teddy bear in the room connected to the kitchen and both bedrooms
- labeled: LR
- ranked: E 0.381 > K 0.286 > LR 0.190 > D 0.048 > B1 0.048 > B2 0.048
- top-1 score: 0.00
- rationale: The kitchen and bedrooms are connected to the entry hall, so that is the most likely room, but other connected rooms are also possible.
- constraint: expected LR; got E, K, B1, B2

### e1_36 (relational): look in the room next to bedroom 2 for a cup
- labeled: LR
- ranked: E 0.891 > K 0.050 > LR 0.030 > D 0.010 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: The room next to bedroom 2 is the entry hall, so most probability goes there.
- constraint: expected LR; got E

### e1_37 (explicit): find the apple
- labeled: K, D
- ranked: E 0.250 > K 0.250 > LR 0.200 > D 0.150 > B2 0.100 > B1 0.050
- top-1 score: 0.50
- rationale: Apples are often eaten in the entry hall or kitchen, but can also be in other rooms.

### e1_38 (explicit): where did I leave the sandwich
- labeled: K, D
- ranked: E 0.412 > K 0.309 > LR 0.206 > D 0.052 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: Sandwiches are often eaten in the entry hall or kitchen, but can also be in the living room or dining area.

### e1_39 (explicit): locate the bowl
- labeled: K, D
- ranked: E 0.412 > K 0.309 > LR 0.206 > D 0.052 > B1 0.010 > B2 0.010
- top-1 score: 0.00
- rationale: Bowl is often used in the entry hall or kitchen, but can be found elsewhere.
