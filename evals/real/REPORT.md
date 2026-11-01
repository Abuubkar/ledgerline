# Real invoices: eval report

Model **gemma4:12b**, prompt `extract-page/4+repair-totals/4`, 25 documents from FCC public files
(evals/golden/real/README.md), replayed on 2026-11-01. **Measured, not gated.**

Scored on what these invoices print: invoice number, invoice date, total (gross or net) and line items, each line
checked only on the values it prints. 2 documents aren't invoices and are listed separately.

| Field | Correct |
|---|---|
| invoice_number | 91.3% |
| invoice_date | 91.3% |
| total_minor | 34.8% |

- Line items: precision 35.3%, recall 39.0%, F1 **37.0%** (104 of 267 gold lines, 295 extracted).
- First-try schema validity: 100.0% of pages.
- Final statuses: exception: 23, extracted: 1, failed: 1.
- Model time per invoice p50 / p95: 279.4 s / 326.4 s; per page p50 / p95: 80.4 s / 147.0 s.

## Documents that aren't invoices

| Case | What it is | Status | Invoice number read | Total read | Gave an invoice number it doesn't have? |
|---|---|---|---|---|---|
| r10 | other | extracted | — | 110500 | no |
| r11 | order | exception | 6282550 | — | **yes** |

## Where it went wrong (19 invoices)

**r01**: status exception
  - total_minor: gold `[478125, 562500]`, got `None`
  - lines: 7 in gold, 18 extracted
  - line `Fox 9 AM News at 6am Political Candidate LUR Rate 6a-7a`: gold 2 × 550.00 = None, got `9 W 02/19/20 :30 6:27 AM MRBPBA3037EH` 2 × 550.0 = None (similarity 33)
  - line `Fox 9 AM News at 6am Political Candidate LUR Rate 6a-7a`: gold 3 × 575.00 = None, got `9 F 02/21/20 :30 6:57 AM MRBPBA3043EH` 3 × 575.0 = None (similarity 35)
  - line `Fox 9 AM News at 7am Political Candidate LUR Rate 7a-8a`: gold 1 × 650.00 = None, got `9 W 02/19/20 :30 7:14 AM MRBPSS325EH` 1 × 650.0 = None (similarity 31)
  - line `M-F 12p-1p Political Candidate CDR Rate 12p-1p`: gold 5 × 125.00 = None, got `9 F 02/21/20 :30 12:59 PM MRBPSS325EH` 5 × 125.0 = None (similarity 32)
  - line `M-F 1p-2p Political Candidate CDR Rate 1p-2p`: gold 5 × 125.00 = None, got `Political Candidate CDR Rate 9 Th 02/20/20 :30 1:20 PM MRBPBA3043EH` 5 × 125.0 = None (similarity 85)
**r03**: status exception
  - total_minor: gold `[3400, 4000]`, got `None`
**r05**: status exception
  - line `Late News M-F 11:00 PM-11:35 PM`: gold 1 × 150.00 = None, got `WVII F 04/03/20 :30 11:12 PM SGTV2008H` 1 × 150.00 = 15000 (similarity 52)
  - line `Late News M-F 11:00 PM-11:35 PM`: gold 1 × 150.00 = None, got `WVII Tu 03/31/20 :30 11:22 PM SGTV2008H` 1 × 150.00 = 15000 (similarity 51)
  - line `Late News M-F 11:00 PM-11:35 PM`: gold 1 × 150.00 = None, got `WVII W 04/01/20 :30 11:19 PM SGTV2008H` 1 × 150.00 = 15000 (similarity 48)
**r06**: status exception
  - total_minor: gold `[1965625, 2312500]`, got `None`
  - lines: 7 in gold, 8 extracted
**r07**: status exception
  - lines: 10 in gold, 16 extracted
  - line `CBS This Morning 7a-9a`: gold 3 × 60.00 = None, got `WYOU F 04/24/20 :30 8:59 AM ABPT2001H` 3 × 60.0 = 18000 (similarity 24)
  - line `CBS Sunday Morning 9a-1030a`: gold 1 × 250.00 = None, got `WYOU Su 04/26/20 :30 9:05 AM ABPT2001H` 1 × 250.0 = 25000 (similarity 41)
  - line `Face the Nation 1030a-11a`: gold 1 × 250.00 = None, got `WYOU Su 04/26/20 :30 11:21 AM ABPT2001H` 1 × 250.0 = 25000 (similarity 32)
  - line `Eyewitness News @ 6p 6p-630p`: gold 3 × 150.00 = None, got `WYOU F 04/24/20 :30 6:10 PM ABPT2001H` 3 × 150.0 = 45000 (similarity 27)
  - line `Eyewitness News @ 6 Sat 6p-630p`: gold 1 × 150.00 = None, got `WYOU W 04/22/20 :30 6:27 PM ABPT2001H` 1 × 150.0 = 15000 (similarity 34)
**r09**: status exception
  - total_minor: gold `[139400, 164000]`, got `None`
  - line `SPOT 2606-TODAY SHOW Day,Th-1`: gold None × None = 11000, got `SPOT 2606-TODAY SHOW Day,Th-1 04/23/20 07:27 am (Th) 00:30 JJWVG0410H` 1.0 × 110.00 = None (similarity 100)
  - line `SPOT 2606-TODAY SHOW Day,F-1`: gold None × None = 8500, got `SPOT 2606-TODAY SHOW Day,F-1 04/24/20 08:27 am (Fr) 00:30 JJWVG0410H` 5.0 × 85.00 = None (similarity 100)
  - line `SPOT 61130-WVVA News Day,Th-1`: gold None × None = 5000, got `SPOT 61130-WVVA News Day,Th-1 04/23/20 12:23 pm (Th) 00:30 JJWVG0410H` 7.0 × 50.00 = None (similarity 100)
  - line `SPOT 61130-WVVA News Day,F-1`: gold None × None = 5000, got `SPOT 61130-WVVA News Day,F-1 04/24/20 12:12 pm (Fr) 00:30 JJWVG0410H` 8.0 × 50.00 = None (similarity 100)
  - line `SPOT 26153-Inside Edition Day,Th-1`: gold None × None = 8500, got `SPOT 26153-Inside Edition Day,Th-1 04/23/20 05:47 pm (Th) 00:30 JJWVG0410H` 11.0 × 85.00 = None (similarity 100)
**r12**: status failed (model_timeout)
  - invoice_number: gold `4055032-1`, got `None`
  - invoice_date: gold `2012-08-26`, got `None`
  - total_minor: gold `[2839000, 3340000]`, got `None`
  - lines: 9 in gold, 0 extracted
**r13**: status exception
  - total_minor: gold `[799000, 940000]`, got `None`
  - lines: 12 in gold, 27 extracted
  - line `8-9a M-F`: gold 2 × 165.00 = None, got `WRAZ W 09/12/12 :30 8:54 AM 2012MRFP094H` 2 × 165.0 = None (similarity 32)
  - line `8-9a M-F`: gold 3 × 165.00 = None, got `WRAZ Th 09/13/12 :30 8:29 AM 2012MRFP094H` 3 × 165.0 = None (similarity 29)
  - line `9-10a M-F`: gold 3 × 100.00 = None, got `WRAZ Th 09/13/12 :30 9:51 AM 2012MRFP094H` 3 × 100.0 = None (similarity 29)
  - line `9-10a M-F`: gold 2 × 100.00 = None, got `WRAZ F 09/14/12 :30 9:45 AM 2012MRFP110H` 2 × 100.0 = None (similarity 50)
  - line `7-730p M-F`: gold 2 × 580.00 = None, got `WRAZ M 09/17/12 :30 7:14 PM 2012MRFP110H` 2 × 580.0 = None (similarity 46)
**r14**: status exception
  - invoice_number: gold `4073029-1`, got `4010263-1`
  - invoice_date: gold `2012-09-30`, got `2012-09-24`
  - total_minor: gold `[126225, 148500]`, got `None`
  - line `Fox 35 5p News`: gold 1 × 630.00 = None, got `Fox: 35 Sp News` 1 × 30.0 = None (similarity 93)
  - line `Fox 35 5p News`: gold 1 × 630.00 = None, got `Fox: 35 Sp News` 30 × 1.0 = None (similarity 93)
  - line `Fox News Sunday`: gold 1 × 225.00 = None, got `For 3 Weeks Sunday` 30 × 1.0 = None (similarity 73)
**r15**: status exception
  - total_minor: gold `[3400000, 4000000]`, got `None`
  - lines: 11 in gold, 13 extracted
  - line `DR PHIL`: gold 5 × 500.00 = None, got `DR PHIL 09/25/2012-09/28/2012` 30 × 500.0 = None (similarity 100)
  - line `JUDGE JUDY SA/SU`: gold 1 × 125.00 = None, got `JUDGE JUDY SA/SU 09/29/2012-10/06/2012` 30 × 125.0 = None (similarity 100)
  - line `CBS13 NEWS @ 5`: gold 5 × 1500.00 = None, got `CBS13 NEWS @ 5 09/25/2012-09/28/2012` 30 × 1500.0 = None (similarity 100)
  - line `THE CLOSER`: gold 1 × 250.00 = None, got `09/24/2012-09/30/2012` 1 × 250.00 = None (similarity 9)
**r16**: status exception
  - total_minor: gold `[3920625, 4612500]`, got `None`
  - lines: 19 in gold, 22 extracted
**r17**: status exception
  - total_minor: gold `[1774375, 2087500]`, got `None`
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-8A/1` None × 625.0 = None (similarity 67)
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-8A/1` None × 625.0 = None (similarity 67)
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-8A/1` None × 625.0 = None (similarity 67)
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-8A/1` None × 625.0 = None (similarity 67)
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-8A/1` None × 625.0 = None (similarity 67)
**r18**: status exception
  - total_minor: gold `[1068875, 1257500]`, got `None`
  - lines: 19 in gold, 18 extracted
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-9A//112` None × 625.00 = None (similarity 67)
  - line `Today Show`: gold None × None = 62500, got `TODAY 7-9A//112` None × 625.00 = None (similarity 67)
  - line `1 preempt @ $625.00`: gold None × None = 0, got `1 pre-empt @ $625.00` None × 0.00 = None (similarity 79)
  - line `JUDGE JUDY 4P`: gold None × None = 40000, got `JUDY 4-430P//114` None × 400.00 = None (similarity 50)
  - line `JUDGE JUDY 4P`: gold None × None = 40000, got `JUDY 4-430P//114` None × 400.00 = None (similarity 50)
**r19**: status exception
  - total_minor: gold `[199750, 235000]`, got `None`
  - line `SPOT 30297-Wake Up Wiscons Day,Th-2`: gold None × None = 25000, got `1.0 SPOT 30297-Wake Up WiscoDnasy,Th-2 05/07/20 6:13AM (Th) 01:00 SWBOWT60` 1.0 × 250.0 = None (similarity 79)
  - line `SPOT 30297-Wake Up Wiscons Day,Th-2`: gold None × None = 25000, got `1.0 SPOT 30297-Wake Up WiscoDnasy,Th-2 05/07/20 6:28AM (Th) 01:00 SWBOWT60` 1.0 × 250.0 = None (similarity 79)
  - line `SPOT 62748-GOOD MORNING AM Day,Th-1`: gold None × None = 25000, got `2.0 SPOT 62748-GOOD MORNINDGa yA,TMh-1 05/07/20 7:59AM (Th) 01:00 SWBOWT60` 2.0 × 250.0 = None (similarity 73)
  - line `SPOT 30368-News 9 WAOW at Day,W-1`: gold None × None = 40000, got `3.0 SPOT 30368-News 9 WAOW Daaty,W-1 05/06/20 6:15PM (We) 01:00 SWBOWT60` 3.0 × 400.0 = None (similarity 88)
  - line `SPOT 30368-News 9 WAOW at Day,Th-1`: gold None × None = 40000, got `4.0 SPOT 30368-News 9 WAOW Daaty,Th-1 05/07/20 6:22PM (Th) 01:00 SWBOWT60` 4.0 × 400.0 = None (similarity 89)
**r20**: status exception
  - line `ABC-Good Morning American Saturday`: gold None × None = 3000, got `SPOT 20374-ABC-Good MornDiany,Sa-1 02/22/20 8:28AM (Sa) 00:30 ABC-Good Morning American SEFTV021820H` 7.0 × 30.0 = 3000 (similarity 85)
  - line `ABC-Good Morning American Saturday`: gold None × None = 3000, got `SPOT 20374-ABC-Good MornDiany,Sa-1 02/22/20 9:25AM (Sa) 00:30 ABC-Good Morning American SEFTV021820H` 9.0 × 30.0 = 3000 (similarity 85)
**r21**: status exception
  - total_minor: gold `[58650, 69000]`, got `None`
  - line `News-Fox 11s Eyewitness News This Morning`: gold None × None = 3500, got `1.0 News 7:00:00AM- 7:30:00ADMay,W-1 03/25/20 7:20AM (We) 00:30 News-Fox 11s Eyewitness News JJWVG0323H This Morning` 0.3 × 35.0 = None (similarity 100)
  - line `News-Fox 11s Eyewitness News This Morning`: gold None × None = 3500, got `2.0 News 7:00:00AM- 7:30:00ADMay,Th-2 03/26/20 7:09AM (Th) 00:30 News-Fox 11s Eyewitness News JJWVG0323H This Morning` 0.3 × 35.0 = None (similarity 100)
  - line `News-Fox 11s Eyewitness News This Morning`: gold None × None = 3500, got `2.0 News 7:00:00AM- 7:30:00ADMay,Th-2 03/26/20 7:25AM (Th) 00:30 News-Fox 11s Eyewitness News JJWVG0323H This Morning` 0.3 × 35.0 = None (similarity 100)
  - line `News-Fox 11s Eyewitness News This Morning`: gold None × None = 3500, got `3.0 News 7:00:00AM- 7:30:00ADMay,F-2 03/27/20 7:09AM (Fr) 00:30 News-Fox 11s Eyewitness News JJWVG0323H This Morning` 0.3 × 35.0 = None (similarity 100)
  - line `News-Fox 11s Eyewitness News This Morning`: gold None × None = 3500, got `3.0 News 7:00:00AM- 7:30:00ADMay,F-2 03/27/20 7:29AM (Fr) 00:30 News-Fox 11s Eyewitness News JJWVG0323H This Morning` 0.3 × 35.0 = None (similarity 100)
**r22**: status exception
  - line `2257415-News-NBC 15 New`: gold None × None = 45000, got `SPOT 2257415-News-NBC 15D aNye,Twu-1,W-1,Th-1,F-1 02/25/20 5:20PM (Tu) 00:30 CFGAAL11H` 3.0 × 150.0 = 45000 (similarity 82)
  - line `2257415-News-NBC 15 New`: gold None × None = 45000, got `SPOT 2257415-News-NBC 15D aNye,Twu-1,W-1,Th-1,F-1 02/26/20 5:24PM (We) 00:30 CFGAAL11H` 3.0 × 150.0 = 45000 (similarity 82)
  - line `2257415-News-NBC 15 New`: gold None × None = 45000, got `SPOT 2257415-News-NBC 15D aNye,Twu-1,W-1,Th-1,F-1 02/27/20 5:22PM (Th) 00:30 CFGAAL11H` 3.0 × 150.0 = 45000 (similarity 82)
  - line `2257415-News-NBC 15 New`: gold None × None = 45000, got `SPOT 2257415-News-NBC 15D aNye,Twu-1,W-1,Th-1,F-1 02/28/20 5:22PM (Fr) 00:30 CFGAAL11H` 3.0 × 150.0 = 45000 (similarity 82)
  - line `2257416-News-NBC 15 New`: gold None × None = 45000, got `SPOT 2257416-News-NBC 15D aNye,Twu-1,W-1,Th-1,F-1 02/25/20 6:14PM (Tu) 00:30 CFGAAL11H` 5.0 × 90.0 = 45000 (similarity 82)
**r23**: status exception
  - total_minor: gold `[30175, 35500]`, got `None`
  - line `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1`: gold None × None = 3500, got `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1 03/09/20 04:11 pm (Mo) 00:30 BFP3020048H` 1.0 × 35.00 = None (similarity 100)
  - line `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1`: gold None × None = 3500, got `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1 03/10/20 04:19 pm (Tu) 00:30 BFP3020039H` 1.0 × 35.00 = None (similarity 100)
  - line `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1`: gold None × None = 3500, got `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1 03/11/20 04:40 pm (We) 00:30 BFP3020039H` 1.0 × 35.00 = None (similarity 100)
  - line `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1`: gold None × None = 3500, got `SPOT 4:00:00PM-5:00:00P Day,M-1Tu-1W-1Th-1 03/12/20 04:11 pm (Th) 00:30 BFP3020048H` 1.0 × 35.00 = None (similarity 100)
  - line `SPOT 4:00:00PM-5:00:00P Day,M-1`: gold None × None = 3500, got `SPOT 4:00:00PM-5:00:00P Day,M-1 03/16/20 04:51 pm (Mo) 00:30 BFP3020048H` 2.0 × 35.00 = None (similarity 100)
**r24**: status exception
  - total_minor: gold `[91800, 108000]`, got `None`
  - line `62748-GOOD MORN`: gold None × None = 10000, got `SPOT 62748-GOOD MORN Day,W-1F-1 03/11/20 08:49 am (We) 00:30 FOCM032030NH` 1.0 × 100.00 = None (similarity 100)
  - line `62748-GOOD MORN`: gold None × None = 10000, got `SPOT 62748-GOOD MORN Day,W-1F-1 03/13/20 08:46 am (Fr) 00:30 FOCM032030NH` None × None = None (similarity 100)
  - line `62748-GOOD MORN`: gold None × None = 10000, got `SPOT 62748-GOOD MORN Day,M-1 03/16/20 08:53 am (Mo) 00:30 FOCM032030NH` 2.0 × None = None (similarity 100)
  - line `109805-HOI ABC Go`: gold None × None = 10000, got `SPOT 109805-HOI ABC Go Day,Tu-1Th-1F-1 03/10/20 06:27 am (Tu) 00:30 FOCM032030NH` 3.0 × None = None (similarity 100)
  - line `109805-HOI ABC Go`: gold None × None = 10000, got `SPOT 109805-HOI ABC Go Day,Tu-1Th-1F-1 03/12/20 06:42 am (Th) 00:30 FOCM032030NH` None × None = None (similarity 100)
