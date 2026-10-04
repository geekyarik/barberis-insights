# Outside-factor feeds for the barbershop tool (Lviv): what is worth building

Researched 2026-10-04 from primary sources only. Legal texts were read directly on zakon.rada.gov.ua (editions "станом на 04.10.2026"); datasets were read through their owners' own catalogues or repositories. Anything I could not trace to a primary source is marked **[UNVERIFIED]**.

## Summary and recommendation per factor

| Factor | Priority (owner) | Recommendation | Why |
|---|---|---|---|
| Public holidays and run-up | High | **Hand-maintained list from the laws** (about 11 dates a year, seeded below). Do not build a feed. | No official API or open dataset for holidays exists (checked data.gov.ua). The law text is short and changed only in 2022-2023; nothing has changed since 14.07.2023. |
| School calendar | (part of Q1) | **Hand-maintained, optional, low value.** | Under martial law school terms are set locally, per school. No single official machine-readable source. |
| Migration / mobilisation | High | **Hand-maintained list of dated legal milestones** (table in section 2). Optionally add the UNHCR border-crossing series as a national context chart, not as a factor. | No Lviv-level time series of men of mobilisation age exists in any primary source I found. Legal milestones are the only defensible, dated, citable proxy. |
| Air-raid alerts | Low | **Skip for now.** If later wanted: import one CSV from an open, MIT-licensed community dataset (section 3), not a live API. | The official-API route (ukrainealarm.com) only exposes the last 25 alerts per region, so it cannot give 2022-2026 history. |
| Competition | Unsure | **Enter by hand** (a dated external factor per opening or closing the owner knows of). | The Unified State Register is open data but gives registered address, not the outlet, and is weekly; Google Places terms forbid caching. |

Not wanted per the owner (power outages, weather, economy): not researched.

---

## 1. Public holidays and school calendar (Ukraine, 2022-2026)

### 1.1 What the sources are

- **The holiday list is Article 73 of the Labour Code** (Кодекс законів про працю, 322-VIII, 10.12.1971): <https://zakon.rada.gov.ua/laws/show/322-08>. The Rada site shows each historical edition (URL pattern `.../322-08/ed20230101`), which is how I read the 2022 and 2023 lists.
- **Martial law suspended the day-off consequences.** Law 2136-IX of 15.03.2022 "Про організацію трудових відносин в умовах воєнного стану", art. 12 part 6 (as amended by Law 2352-IX of 01.07.2022): for the duration of martial law, art. 53, art. 65 part 1, art. 67 parts 3-5 and arts. 71, 73 (and others) of the Labour Code are not applied. Text: <https://zakon.rada.gov.ua/laws/show/2136-20>. Published in Голос України 23.03.2022, so in force from 24.03.2022 (the law's own clause "з дня, наступного за днем опублікування"; Голос України date shown on the page). Art. 73 itself carries the note "У період дії воєнного стану не застосовуються норми статті 73".
  - Practical meaning: the holiday dates still exist in the code, but since 24.03.2022 they are not statutory days off, and shortened pre-holiday working days (art. 53) do not apply. The Cabinet's usual "working-day transfer" orders are not issued during martial law (I found none after 2021; see 1.3).
  - Martial law is still in force: latest extension is Decree 596/2026 (from 05:30 on 02.08.2026, 90 days), <https://zakon.rada.gov.ua/laws/show/596/2026> (read from the search result for this page; I did not open the decree text).
- **The Constitutional Court ruling of 19.05.2026** on Law 2136-IX (<https://zakon.rada.gov.ua/laws/show/va03p710-26>) was checked: its operative part concerns annual-leave rules (art. 12 part 1) and para. 3 of the final provisions, not the suspension of art. 73.
- **No official API or open dataset for holidays.** I queried the national open-data portal catalogue API (`data.gov.ua/api/3/action/package_search`) for "святкові дні", "календар свят", "неробочі дні", "перенесення робочих днів": no dataset from a state body containing the holiday calendar (hits were municipal transport timetables and mayoral orders). The Rada publishes an HTML-only "Календар офіційних свят": <https://zakon.rada.gov.ua/laws/main/days> (I could not extract content programmatically; treat as a human page).
- Conclusion: **a small hand-maintained table citing the laws below is the correct approach.**

### 1.2 Laws that changed the list (exact, verified from the law texts)

| Law | Date | What it changed | Source |
|---|---|---|---|
| Labour Code art. 73, edition of 01.01.2022 | pre-war | 1 Jan; **7 Jan and 25 Dec** Christmas; 8 Mar; 1 May; **9 May** Victory Day; 28 Jun Constitution Day; 24 Aug Independence Day; **14 Oct** Defenders Day; Easter Sunday and Trinity Sunday (religious days) | <https://zakon.rada.gov.ua/laws/show/322-08/ed20220101> |
| 2136-IX | 15.03.2022 | Art. 73 (and 53, 67, 71 etc.) not applied during martial law, in force 24.03.2022 | <https://zakon.rada.gov.ua/laws/show/2136-20> |
| 2295-IX | 31.05.2022 | Added **28 July** "День Української Державності"; in force day after publication (Голос України 08.06.2022, so from 09.06.2022) | <https://zakon.rada.gov.ua/laws/show/2295-20> |
| 3107-IX | 29.05.2023 | 9 May Victory Day replaced by **8 May** "День пам'яті та перемоги над нацизмом"; in force day after publication (Голос України 14.06.2023, so from 15.06.2023). First 8 May observed: 2024 | <https://zakon.rada.gov.ua/laws/show/3107-20> |
| 3258-IX | 14.07.2023 | Removed **7 Jan** Christmas (keeps **25 Dec** Christmas, also as a religious day); Statehood Day **28 Jul to 15 Jul**; Defenders Day **14 Oct to 1 Oct**. In force the day after publication (Голос України 29.07.2023, so from 30.07.2023) | <https://zakon.rada.gov.ua/laws/show/3258-20> |

- The history footer of art. 73 on 04.10.2026 lists no amending law after 3258-IX (list ends: 1643-IX, 2295-IX, 3107-IX, 3258-IX), so **the 2023 list is still the current one**: 1 Jan, 8 Mar, 1 May, 8 May, 28 Jun, 15 Jul, 24 Aug, 1 Oct, 25 Dec, plus Easter Sunday and Trinity Sunday.
- **Correction to the brief:** Constitution Day (28 June) and Independence Day (24 August) were **not moved** by any law; I checked every edition. What moved: Christmas (7 Jan to 25 Dec), Statehood Day (28 Jul to 15 Jul), Defenders Day (14 Oct to 1 Oct), Victory Day (9 May to 8 May).
- Whether 2023 observed Statehood Day on 15 Jul or 28 Jul in practice is **[UNVERIFIED]** (the law passed 14 Jul 2023 but only entered force 30 Jul 2023; by the code text 28 Jul applied in 2023). Likewise the first observed Defenders Day on 1 Oct is 2023 by the code text.
- Easter and Trinity are not set by any law: art. 73 only says "Пасха (Великдень)" and "Трійця" Sundays. The dates below are the Orthodox Paschal dates, computed with the standard algorithm; **not from a state source [UNVERIFIED against a church calendar]**. Note that in 2025 East and West Easter coincide (20 Apr).

### 1.3 Pre-war working-day transfers (2022 only)

- Cabinet order 1004-р of 26.08.2021 recommended employers move Mon 7 Mar to Sat 12 Mar and Mon 27 Jun to Sat 2 Jul 2022, making 5-8 Mar and 25-28 Jun long weekends: <https://zakon.rada.gov.ua/laws/show/1004-2021-%D1%80>. This was a recommendation and, after 24.03.2022, art. 73 days are not days off. Whether anything was actually applied on 7 Mar and 27 Jun 2022 is **[UNVERIFIED]**. No such orders for 2023-2026 were found (not exhaustively searched).

### 1.4 Verified list of holiday dates, 2022-2026 (code text; weekday computed)

"Code" = date listed in art. 73 in force that year. None is a statutory day off after 24.03.2022. Weekday is what matters for the shop.

| Year | Fixed dates (weekday) | Easter / Trinity (Orthodox, computed) |
|---|---|---|
| 2022 | 1 Jan Sat; 7 Jan Fri; 8 Mar Tue; 1 May Sun; 9 May Mon; 28 Jun Tue; 28 Jul Thu; 24 Aug Wed; 14 Oct Fri; 25 Dec Sun | 24 Apr / 12 Jun |
| 2023 | 1 Jan Sun; 7 Jan Sat; 8 Mar Wed; 1 May Mon; 9 May Tue (8 May Mon from 15.06.2023, i.e. not yet in force on the day); 28 Jun Wed; 28 Jul Fri; 24 Aug Thu; 1 Oct Sun (code from 30.07.2023; 14 Oct Sat before); 25 Dec Mon | 16 Apr / 4 Jun |
| 2024 | 1 Jan Mon; 8 Mar Fri; 1 May Wed; 8 May Wed; 28 Jun Fri; 15 Jul Mon; 24 Aug Sat; 1 Oct Tue; 25 Dec Wed | 5 May / 23 Jun |
| 2025 | 1 Jan Wed; 8 Mar Sat; 1 May Thu; 8 May Thu; 28 Jun Sat; 15 Jul Tue; 24 Aug Sun; 1 Oct Wed; 25 Dec Thu | 20 Apr / 8 Jun |
| 2026 | 1 Jan Thu; 8 Mar Sun; 1 May Fri; 8 May Fri; 28 Jun Sun; 15 Jul Wed; 24 Aug Mon; 1 Oct Thu; 25 Dec Fri | 12 Apr / 31 May |

Edition checks: 01.01.2022 and 01.01.2023 editions (links in 1.2 pattern) list 7 Jan and 25 Dec as Christmas; the 2023 edition adds 28 Jul.

### 1.5 Dates that matter for a barbershop (run-up)

The law only defines the holiday itself. Run-up windows are a modelling choice, not sourced; propose these as recurring factors and let the shop's own 2022-2026 history measure the effect **[hypotheses, not from any source]**:

- New Year: 24-31 Dec (and 25 Dec itself, now a holiday); 1 Jan after-effect.
- 8 Mar: 5-7 Mar (men's visits before the holiday are plausible; test it).
- Easter: Thursday to Saturday before the computed Sunday; Trinity weekend.
- 8 May, 1 May, 28 Jun, 24 Aug, 1 Oct, 15 Jul: the 1-2 days before when the holiday is mid-week or Monday/Friday (long weekends in practice, even though not statutory days off now).
- 7 Jan (Orthodox Christmas, not a code date after 30.07.2023) and 14 Feb, 23 Feb: customs, not law. Include only if the owner wants them.

### 1.6 School year and school holidays

| Source | What it says | Notes |
|---|---|---|
| Cabinet resolution 1003 of 20.08.2025 "Про початок навчального року під час воєнного стану" | 2025/2026 school year: 1 Sep 2025 to 30 Jun 2026; start of the year depends on the security situation per oblast; applies during martial law. <https://zakon.rada.gov.ua/laws/show/1003-2025-%D0%BF> | Read in full. |
| MON news on 2025/26 organisation | Ministry-level framework (Order 1112 on schooling in martial law is named in the search result). <https://mon.gov.ua/news/mon-zatverdylo-osoblyvosti-orhanizatsii-navchannia-u-zzso-na-2025-2026-navchalnyi-rik> | Page fetched but yielded no usable text; Order 1112 content **[UNVERIFIED]**. |
| Lviv City Council (founder) pages on autumn, winter, spring breaks | Owns the Lviv dates; each school sets its own within the framework. <https://city-adm.lviv.ua/news/society/education/koly-uchni-lvivskykh-shkil-idut-na-osinni-kanikuly/>, <https://city-adm.lviv.ua/news/society/education/koly-lvivski-uchni-pidut-na-zymovi-kanikuly-hrafik/>, <https://city-adm.lviv.ua/news/society/education/koly-lvivski-uchni-pidut-na-vesniani-kanikuly-hrafik/> | Pages exist (search result titles) but I could not retrieve their text, so **dates are UNVERIFIED**. A media summary (not primary) gave autumn 24 Oct to 3 Nov 2025 and winter 24 Dec 2025 to 11 Jan 2026 for most schools; use only as a lead. |

Recommendation: do not build a school feed. Under martial law there is no single national holiday calendar; if wanted, the owner enters the 2-3 break windows per year from the Lviv City Council pages (and 1 Sep and the June finish).

### 1.7 Options table (Q1)

| Source | Measures | Granularity | History | Licence / API | Reliability |
|---|---|---|---|---|---|
| Labour Code art. 73, with edition history (zakon.rada.gov.ua) | Statutory holidays and their changes | Date | All editions since 1971; 2022-2026 covered | Public legal text; no API for this (HTML, "print" view) | Authoritative; but Easter/Trinity not dated; day-off effect suspended since 24.03.2022 |
| Law 2136-IX | Suspension of art. 73 in martial law | Period | From 24.03.2022 | Same | Authoritative |
| Cabinet transfer orders (1004-р for 2022) | Recommended working-day swaps | Date | Only until 2022 | Same | Recommendation only |
| data.gov.ua catalogue | (no holiday dataset) | n/a | n/a | CKAN API exists | Nothing relevant found |
| Cabinet res. 1003-2025-п; Lviv City Council pages | School year / breaks | Year / school | 2025/26 | Same | Breaks set by each school |

---

## 2. Migration and mobilisation

### 2.1 Findings by source

| Source | What it measures | Reaches Lviv? | Grain | History | Update | Licence / API | Reliability caveats |
|---|---|---|---|---|---|---|---|
| **UNHCR Operational Data Portal, Ukraine refugee situation** <https://data.unhcr.org/en/situations/ukraine> | Refugees recorded abroad; border crossings from/to Ukraine (as reported by neighbouring states' border authorities); asylum/temporary-protection counts | **No** (national totals by neighbouring country) | Daily for crossings; monthly or quarterly for the rest | Since 24.02.2022 (explanatory note) | Monthly or per authority | **CC BY 4.0** ("Except where otherwise indicated"), per the portal's Data Explanatory Note <https://data.unhcr.org/en/working-group/437>. The note and search results indicate JSON/CSV exports; the exact API endpoint I did **not** verify | Crossings "reflect cross-border movements, not unique individuals"; since **May 2025 methodology** counts **Ukrainian nationals only**, so series before and after are not comparable without care; no sex or age split in the crossing series; figures rounded to nearest 5; pendular movement. A national outflow is a weak proxy for Lviv men. |
| **IOM DTM Ukraine, IDP Estimates** (HDX) <https://data.humdata.org/dataset/ukraine-idp-estimates> | Estimated IDPs by area of current location, from General Population Survey rounds | Oblast level (Lviv oblast is one row); finer layers exist in other DTM products **[UNVERIFIED]** | Rounds: R1 16.03.2022 up to R23 March 2026; 23 rounds in about 4 years, so roughly every 1-3 months, and sparser later (R19 Dec 2024, R20 Apr 2025, R21 Oct 2025, R22 Dec 2025, R23 Mar 2026) | 16.03.2022 to 03.2026 (HDX metadata read via its API) | Declared update frequency 180 days | HDX licence "Other": **IOM text allows non-commercial use only, no redistribution or derivatives**, with credit to "IOM, DTM". Check before using in a commercial product. Data is XLSX downloads (no real-time API) | Measures displaced people **stock** (all sexes and ages), not men of mobilisation age; survey-based, representative at macro-region level in early rounds per the dataset notes, so oblast figures carry error **[to verify per round]** |
| **State Border Guard Service (ДПСУ)** <https://dpsu.gov.ua/ua/Vidkriti-dani/> | Open-data page; news releases with crossing totals (e.g. "from the start of 2026 about 20.7 million crossings, 18 million by Ukrainian citizens", per a ДПСУ news item) | Not found at Lviv level or by sex as a time series | Press releases only | n/a | Irregular | The open-data page I found lists organisational datasets; the "Електронна черга перетину кордону" dataset on data.gov.ua (<https://data.gov.ua/dataset/a8909a08-4da6-49c5-9238-6ab227059c51>) covers vehicle queue bookings at checkpoints | **No published time series of men crossing; none by oblast or by sex** found. |
| **State Statistics Service (Ukrstat)** | Population estimates | I did not find a current regional or sex-by-age series | n/a | n/a | n/a | n/a | **[UNVERIFIED]** I did not retrieve a Ukrstat source. Stated as "not found", not as "does not exist". |
| **Legislation** (below) | Rules on who may be mobilised and who may leave | National rules, apply in Lviv | Date-exact | 2022-present | Event-driven | Public legal text, zakon.rada.gov.ua | Rules, not counts; enforcement intensity and public perception vary |

### 2.2 Verified legal milestones (dated factor candidates)

| Date | Event | Source |
|---|---|---|
| 24.02.2022 | Decree 69/2022: general mobilisation announced across 25 listed regions, **including Lviv oblast** (first period 90 days); in force from 24.02.2022 | <https://zakon.rada.gov.ua/laws/show/69/2022> |
| 24.03.2022 | Labour-law martial-law regime in force (Law 2136-IX) | <https://zakon.rada.gov.ua/laws/show/2136-20> |
| from 28.02.2022 | Border-crossing Rules (Cabinet res. 57 of 27.01.1995) amended in the first days of the war (res. 166 of 28.02.2022 appears in the amendment history). That men of mobilisation age are barred from leaving is widely stated, but the **exact 18-60 clause and its start date I did not verify** | <https://zakon.rada.gov.ua/laws/show/57-95-%D0%BF> **[UNVERIFIED clause]** |
| 11.04.2024 signed; **in force 18.05.2024** | Law 3633-IX on military service, mobilisation and military registration (military records updating; mandatory update of data within 60 days; many changes). Published in Голос України 17.04.2024; in force one month after the day following publication (some parts later). | <https://zakon.rada.gov.ua/laws/show/3633-20> (publication date read; 18.05.2024 is derived from the stated rule and matches Cabinet res. 563-2024-п's date per the search result) |
| 2024-2025 | Law 3621-IX of 21.03.2024 on social protection of servicemen (amended by 4235-IX of 12.02.2025): moves persons aged 25-60 previously declared "partly fit" to re-examination by 05.06.2025. The **lower mobilisation age of 25** is part of this reform line, but the exact article and the date it took effect I did not confirm | <https://zakon.rada.gov.ua/laws/show/3621-20> **[age-25 provision UNVERIFIED]** |
| from 01.09.2025 | Part of Law 3633-IX provisions start (basic military service etc.; the law text says "розпочинається з 1 вересня 2025 року") | <https://zakon.rada.gov.ua/laws/show/3633-20> |
| **26.08.2025** (published Урядовий кур'єр 28.08.2025, so in force about 28.08.2025 **[exact date UNVERIFIED]**) | Cabinet res. 1031: during martial law the exit restriction **does not apply to men aged 18-22 inclusive** (passport plus military registration document required). The current Rules text (57-95-п) carries the same rule | <https://zakon.rada.gov.ua/go/1031-2025-%D0%BF>; current Rules <https://zakon.rada.gov.ua/laws/show/57-95-%D0%BF>; Cabinet explainer <https://www.kmu.gov.ua/news/roziasnennia-mvs-shchodo-vyizdu-za-kordon-cholovikiv-vikom-18-22-rokiv-vkliuchno> |
| Martial law extensions | Every 90 days; last verified: Decree 596/2026 from 02.08.2026 | <https://zakon.rada.gov.ua/laws/show/596/2026> |

Not yet checked and worth adding by hand if the owner agrees: mobilisation-wave milestones (e.g. TCC enforcement campaigns), booking-exemption (бронювання) resolutions such as 76/2023 and 233-2025-п, and any changes after 28.08.2025. Cabinet res. 233 of 2025 appears in search results as "Деякі питання бронювання" (<https://zakon.rada.gov.ua/laws/show/233-2025-%D0%BF>); content **[UNVERIFIED]**.

### 2.3 Most defensible approach

No primary source gives a time series of men of mobilisation age present in Lviv. The honest options:

1. **Hand-entered milestone list** (table 2.2) as dated `external` records at day grain, scope shop, no recurrence. Effects are measured from the shop's own history: for example share of male clients, new vs returning men, visit frequency before vs after each date.
2. Better evidence is **inside the CRM**: share of clients who are men aged roughly 18-60, active-client counts by cohort. That is the proxy that actually reflects what the owner cares about, and needs no feed.
3. UNHCR crossings as a **national background chart** only (CC BY 4.0; mind the May 2025 methodology break). IOM DTM is oblast-level IDPs and sparse, with a non-commercial licence: skip.

---

## 3. Air-raid alerts (low priority)

### 3.1 Findings

- **Ukraine Alarm API** (api.ukrainealarm.com, key by request form). Official client libraries from the project owner show the endpoints: `GET /api/v3/alerts` (current alerts), `GET /api/v3/alerts/regionHistory` ("Отримати останніх 25 тривог регіону"), `GET /api/v3/alerts/{regionId}`, `GET /api/v3/alerts/status`. Source: <https://github.com/UkraineAlarm/UkraineAlarm-javascript>, <https://github.com/UkraineAlarm/UkraineAlarm-python>, <https://github.com/PaulAnnekov/ukrainealarm> (API key via form on <https://api.ukrainealarm.com/>). The API site itself returns 403 to my requests (Cloudflare), so the API's own terms and rate limits are **[UNVERIFIED]**. **History is limited to the last 25 alerts per region**, so it cannot backfill 2022.
- **alerts.in.ua API** (<https://devs.alerts.in.ua/>): token by form; history endpoint `/v1/regions/{uid}/alerts/{period}.json` with `period` such as `month_ago` (so about a month back, not years); limits: soft 8-10 requests/min per IP, hard 12/min (429 over limit); 403 if API unavailable in your country; disclaimer: "Не використовуйте API для критичної інфраструктури", use at your own risk, delays possible. The service states its data come from "офіційне АРІ, канал 'Повітряна тривога', ОВА, Суспільне, ДСНС" (own docs). A private service, not the data owner.
- **Official owner:** the alert signal chain (the Ministry of Digital Transformation "Повітряна тривога" app and the official Telegram channel) is named by alerts.in.ua as a source; I did **not** find a primary government page documenting an official historical dataset or API terms **[UNVERIFIED]**.
- **Historic dataset:** community repo <https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset>, **MIT licence**, updated daily (README), CSV files in `datasets/`:
  - `official_data_uk.csv`: from **15.03.2022**; columns `oblast, raion, hromada, level, started_at, finished_at, source`; times in UTC. Since late 2025 mostly raion-level (README); in the file raion rows begin 2025-09-03.
  - `volunteer_data_uk.csv`: from **25.02.2022**, oblast level only, from the eTryvoga Telegram channel; entries with no end message are flagged `naive=True` with end = start + 30 min.
  - Permanent sirens (Luhansk, Crimea) are excluded.
  - Who maintains it: an individual (GitHub user Vadimkin); the "official" label refers to its source, which the README does not document in detail **[UNVERIFIED]**.
- **What the data shows for Lviv oblast** (I downloaded the official file and counted oblast-level rows; this is for sizing only, not a result of the shop analysis):

| Year | Oblast-level alerts | Total alert hours |
|---|---|---|
| 2022 (from 15 Mar) | 460 | 507 |
| 2023 | 382 | 458 |
| 2024 | 418 | 410 |
| 2025 (oblast level only; raion rows from 3 Sep) | 230 | 248 |

  Alerts are frequent (more than one a day on average), so "alert day" as a binary factor would be nearly always on; the interesting variables would be night alerts, long alerts (over 3 hours) or alerts overlapping opening hours. That fits the owner's "rare impact" view and supports low priority.

### 3.2 Options table (Q3)

| Source | What it measures | Granularity | History | Licence / API | Reliability |
|---|---|---|---|---|---|
| api.ukrainealarm.com | Current and last 25 alerts per region | Oblast, raion, hromada | Last 25 per region only | Key by form; terms unverified | Good for live, useless for history |
| alerts.in.ua API | Active alerts, history by period | Oblast and below | About a month | Token by form; 12 req/min hard limit; use at own risk | Private service; delays possible |
| Vadimkin dataset (GitHub) | All siren records | Oblast (raion since 2025-09) | 15.03.2022 (official), 25.02.2022 (volunteer) to today | MIT; static CSV, daily refresh | Volunteer-maintained; source chain not documented; long gaps or naive end times possible in the volunteer file |

Recommendation: skip now; if the owner later wants it, one-off import of the CSV, filtered to Львівська область, into day or hour-level factors.

---

## 4. Competition (short)

- **Unified State Register (ЄДР)** open data on data.gov.ua, owner Ministry of Justice: dataset "Єдиний державний реєстр юридичних осіб, фізичних осіб-підприємців та громадських формувань", licence **Creative Commons Attribution**, files UO.zip, FOP.zip, FSU.zip plus schemas, catalogue metadata updated 2026-09-29, update frequency "once a week": <https://data.gov.ua/dataset/a1799820-195b-4982-8141-6e84f58103e7> (via the CKAN API). It lists registration dates and registered addresses and, by the dataset notes, state registration dates, so it could date new sole traders or companies, but: the address is the registered office (often the owner's home), there is no outlet-level data, KVED filtering (96.02 hairdressing) and geocoding would be needed, and I did not verify the field list. Opening a barbershop is not the same as registering a FOP.
- **Google Places API:** the Service Specific Terms allow caching of `place_id` indefinitely, but other Places content (including latitude and longitude) only for up to 30 consecutive calendar days, then deletion or replacement; and Places API policy says "You must not pre-fetch, cache, or store Places API content beyond the allowed exceptions": <https://cloud.google.com/maps-platform/terms/maps-service-terms>, <https://developers.google.com/maps/documentation/places/web-service/policies>. Places also does not expose opening dates, so it cannot date a competitor opening.
- Recommendation: **enter by hand.** One external record per known opening or closure, scope shop, day grain, no recurrence.

---

## Sources

Legal texts (all zakon.rada.gov.ua, read 2026-10-04):
- <https://zakon.rada.gov.ua/laws/show/322-08> (Labour Code; editions `/ed20220101`, `/ed20230101`)
- <https://zakon.rada.gov.ua/laws/show/2136-20> (Law 2136-IX)
- <https://zakon.rada.gov.ua/laws/show/2352-20> (Law 2352-IX)
- <https://zakon.rada.gov.ua/laws/show/2295-20> (Law 2295-IX)
- <https://zakon.rada.gov.ua/laws/show/3107-20> (Law 3107-IX)
- <https://zakon.rada.gov.ua/laws/show/3258-20> (Law 3258-IX)
- <https://zakon.rada.gov.ua/laws/show/va03p710-26> (Constitutional Court ruling 19.05.2026)
- <https://zakon.rada.gov.ua/laws/show/1004-2021-%D1%80> (transfer order for 2022)
- <https://zakon.rada.gov.ua/laws/show/1003-2025-%D0%BF> (school year 2025/26 in martial law)
- <https://zakon.rada.gov.ua/laws/show/596/2026> (martial law extension; from search result)
- <https://zakon.rada.gov.ua/laws/show/69/2022> (general mobilisation decree)
- <https://zakon.rada.gov.ua/laws/show/3633-20> (Law 3633-IX)
- <https://zakon.rada.gov.ua/laws/show/3621-20> (Law 3621-IX)
- <https://zakon.rada.gov.ua/laws/show/2232-12>, <https://zakon.rada.gov.ua/laws/show/3543-12> (Law on military duty; Law on mobilisation preparation; read for age references)
- <https://zakon.rada.gov.ua/go/1031-2025-%D0%BF> (Cabinet res. 1031)
- <https://zakon.rada.gov.ua/laws/show/57-95-%D0%BF> (Border-crossing Rules)
- <https://zakon.rada.gov.ua/laws/show/233-2025-%D0%BF> (booking; not read)
- <https://zakon.rada.gov.ua/laws/main/days> (holiday calendar page; not extracted)
- <https://www.kmu.gov.ua/news/roziasnennia-mvs-shchodo-vyizdu-za-kordon-cholovikiv-vikom-18-22-rokiv-vkliuchno>

Data owners and catalogues:
- <https://data.gov.ua> (CKAN API queried: `/api/3/action/package_search`)
- <https://data.gov.ua/dataset/a1799820-195b-4982-8141-6e84f58103e7> (Unified State Register open data)
- <https://data.gov.ua/dataset/a8909a08-4da6-49c5-9238-6ab227059c51> (ДПСУ electronic queue data)
- <https://dpsu.gov.ua/ua/Vidkriti-dani/> (ДПСУ open data page)
- <https://data.unhcr.org/en/situations/ukraine>, <https://data.unhcr.org/en/working-group/437> (UNHCR data explanatory note, CC BY 4.0)
- <https://data.humdata.org/dataset/ukraine-idp-estimates> (IOM DTM IDP estimates, read via HDX API)
- <https://mon.gov.ua/news/mon-zatverdylo-osoblyvosti-orhanizatsii-navchannia-u-zzso-na-2025-2026-navchalnyi-rik> (not retrievable)
- Lviv City Council school break pages (listed in 1.6; not retrievable)

Alerts:
- <https://api.ukrainealarm.com/> (blocked to my client), <https://github.com/UkraineAlarm/UkraineAlarm-javascript>, <https://github.com/UkraineAlarm/UkraineAlarm-python>, <https://github.com/PaulAnnekov/ukrainealarm>
- <https://devs.alerts.in.ua/>
- <https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset> (MIT; `datasets/README.md`, `official_data_uk.csv`, `volunteer_data_uk.csv`)

Competition:
- <https://cloud.google.com/maps-platform/terms/maps-service-terms>
- <https://developers.google.com/maps/documentation/places/web-service/policies>

Main gaps: school-break dates for Lviv; exact 18-60 exit-ban clause and start date; the age-25 mobilisation provision; ukrainealarm.com terms and limits; any Ukrstat series; UNHCR JSON endpoint; Easter dates against a church calendar.
