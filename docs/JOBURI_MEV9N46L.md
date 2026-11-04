# Joburi EDIABAS verificate pe MEV9N46L (doar citire)

Toate au răspuns `OKAY`. Valorile în paranteză sunt exemple la ralanti cald dacă nu se spune altfel. Semnificațiile marcate „?" nu sunt sigure.

STATUS_MESSWERTE (un singur apel, aproximativ 25 de valori: jobul principal pentru bucla rapidă):
- `STAT_NMOT_WERT` turația (708,5 rpm); `STAT_NSOL_WERT` turația-țintă (700)
- `STAT_TMOT_WERT` temperatura motorului; `STAT_TANS_WERT` temperatura aerului admis; `STAT_TKA_WERT` (?)
- `STAT_UB_WERT` tensiune (14,13 V); `STAT_VFZG_WERT` viteza mașinii (km/h)
- `STAT_UPWG_WERT` tensiunea pedalei (0,718 V)
- `STAT_MSHFM_WERT` masa de aer MAF (5,6 kg/h)
- `STAT_MIIST_WERT` cuplul efectiv (9,19 %)
- `STAT_FR_WERT` / `STAT_FR2_WERT` factorii de reglare lambda bancă 1 / 2 (0,987 / 1,005)
- `STAT_TE_WERT` timpul de injecție (2,848 ms)
- `STAT_WDKBA_WERT` deschiderea clapetei (2,75 %DK); `STAT_ZWOUT_WERT` avansul (12°)
- `STAT_WNWKWA_WERT` / `STAT_WNWKWE_WERT` unghiul arborelui cu came evacuare / admisie (600,8 / 620,2 °KW)
- `STAT_RKRN0_WERT` … `STAT_RKRN3_WERT` (V; ? posibil nivel de referință la detecția de detonație pe cilindru). RKRN4..7 = 0.

STATUS_FASTA2 (conține SARCINA motorului):
- `STAT_RL_WERT` SARCINA relativă / umplere cu aer (14,7 %); `STAT_RLSOL_WERT` sarcina-țintă (15,1 %)
- `STAT_WPED_WERT` pedala (%PED, 0 la ralanti); `STAT_WDKS_WERT` clapeta (3,05 %)
- `STAT_MIMIN_WERT` cuplu minim (10,6 %); `STAT_ZWIST_WERT` avans efectiv (15 °KW)
- `STAT_TE_WERT` (2,856 ms) și `STAT_TE2_WERT` (2,336 ms): diferă mult, semnificația lui TE2 e neclară (?)
- `STAT_DMLLRI_WERT` integratorul regulatorului de ralanti (−1,05 %); `STAT_NSOLFASTA_WERT` (700); `STAT_VVTSTATUS_WERT` (255); `STAT_WDKBAFASTA_WERT` (3,03); `STAT_MIL_EIN` (0)

STATUS_FASTA1: `STAT_DPS_WERT` (47,7 hPa), `STAT_TSG_WERT` temperatura calculatorului (39,75 °C), `STAT_DMVAD_WERT`, `STAT_FKMSVVT_WERT`, `STAT_LRNSTEP_WERT`, `STAT_MSNVVTO_WERT`, `STAT_NNW10..22`, `STAT_DPSRAUS_WERT` (177814, valoare neplauzibilă, ignoră).

STATUS_LAUFUNRUHE (neregularitate pe cilindri, sec⁻¹, abateri de la medie; suma ≈ 0):
- `STAT_LUTSFI1_WERT` … `STAT_LUTSFI4_WERT` (abateri față de medie, suma ≈ 0). LUTSFI5..8 nefolosite.
- `STAT_UULSUV_WERT`, `STAT_UULSUV2_WERT` (tensiunile sondelor lambda), `STAT_FOFR1_EIN`.

STATUS_FUNKTIONSSTATI (biți de stare, `_EIN` 0/1): `STAT_LL_EIN` (reglare ralanti), `STAT_LR_EIN` și `STAT_LR2_EIN` (reglare lambda pe bănci), `STAT_LRNRDY_EIN`, `STAT_KD_EIN`, `STAT_PN_EIN`, `STAT_SA_EIN`, `STAT_VL_EIN`, `STAT_TEHB_EIN`, `STAT_SBBHK_EIN`, `STAT_SBBVK_EIN`, `STAT_SBBHK2_EIN`, `STAT_SBBVK2_EIN`, `STAT_ECULOCK_EIN`.

Sonde lambda: `STATUS_L_SONDE` → `STAT_L_SONDE_WERT` (înainte de cat, b1), `STATUS_L_SONDE_2` → `STAT_L_SONDE_2_WERT` (b2), `STATUS_L_SONDE_H` → `STAT_L_SONDE_H_WERT` (după cat, b1), `STATUS_L_SONDE_2_H` → `STAT_L_SONDE_2_H_WERT` (b2). Toate în V.

STATUS_GEMISCH (adaptări de amestec memorate, se schimbă lent): `STAT_FRA_WERT`, `STAT_FRA2_WERT`, `STAT_RKAT_WERT`, `STAT_RKAT2_WERT`, `STAT_TEDUB_WERT`, `STAT_TEDUB2_WERT`, `STAT_DYNLSU_WERT`, `STAT_DYNLSU2_WERT`, `STAT_LAMSONI_WERT`, `STAT_LAMSONI2_WERT`.

STATUS_VVT (Valvetronic): `STAT_VVTIW_WERT` (efectiv) / `STAT_VVTSW_WERT` (țintă) se potrivesc; `STAT_VVTIW2_WERT` / `STAT_VVTSW2_WERT` NU se potrivesc (7,4 vs 4,5; semnificație ?); `STAT_VVTES_WERT`, `STAT_VVTES2_WERT`, `STAT_VVTTV_WERT`, `STAT_VVTTV2_WERT`, `STAT_MINHUB*`, `STAT_FLUB1/2_WERT`, `STAT_DELTAGVFI_WERT`.

Alte joburi care merg: `STATUS_MOTORDREHZAHL`, `STATUS_MOTORTEMPERATUR`, `STATUS_AN_LUFTTEMPERATUR`, `STATUS_UBATT`, `STATUS_LMM_MASSE`, `STATUS_PWG_POTI_SPANNUNG` (`..._1_WERT`, `..._2_WERT`), `STATUS_LLABG` (toate 0), `STATUS_GEBERRAD_ADAPTION` (`VSA`, `VSE`, `VSA_2`, `VSE_2`; 6553,5 = probabil neînvățat), `STATUS_READINESS`, `STATUS_DKHFM`, `STATUS_SAUGROHR`, `STATUS_SYSTEMCHECK_KAT`, `STATUS_SYSTEMCHECK_LAMBDA_AUS` (textul lui NU e un indicator de încredere al regimului lambda).

Identificare și erori: `IDENT`, `ZIF_LESEN`, `DATEN_REFERENZ_LESEN`, `HARDWARE_REFERENZ_LESEN`, `AIF_LESEN` (conține VIN), `FS_LESEN`, `FS_LESEN_DETAIL` (parametru: numărul erorii în zecimal, ex. `11107` pentru 0x2B63).

Lista completă a celor 64 de joburi `STATUS_*` e în `BMW_CONTEXT.md`. Pentru un job nou: rulează-l o dată fără filtru, uită-te la rezultate, apoi adaugă-l în profil.
