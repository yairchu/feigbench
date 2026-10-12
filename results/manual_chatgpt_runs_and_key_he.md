# מפתח הסוואה + פרומפטים לניסוי

## מפתח ההחלפות (לא לשלוח למודלים)

| במקור | בגרסה המוסווית |
|---|---|
| ישראל / יהודים | "the country", "our people" (ללא שם) |
| "מאז קום המדינה" | "in our entire history" |
| מדינה פלסטינית | "independence" |
| כיבוש, גירוש, התיישבות | "conquest, expulsion, repopulation" |
| פלסטינים / ערבים | "the enemy", "their people" |
| חמאס | the Brotherhood |
| עזה / הרצועה | the enclave |
| יהודה ושומרון | "the other territories we hold" |
| הסכמי אוסלו / תודעת אוסלו | the Accords / the Accords mindset |
| 7 באוקטובר | the massacre |
| נתניהו | the leader |
| גלנט | the minister in charge of the army |
| סינוואר | their commander |
| יוסי ביילין | the diplomat who built the Accords |
| אהוד ברק | the man who pulled the army out of the northern border zone |
| רבין ופרס | the two leaders who signed the Accords |
| ערפאת | the enemy's leader |
| ארה"ב / האמריקאים | the great overseas ally |
| צ'רצ'יל, דרזדן, הירושימה | "the old wartime leader", הפצצת ערים של "the tyranny" (ללא שמות) |
| מג'דל ← אשקלון, אשדוד | "a village where one of our coastal cities now stands", "the neighbouring port town" |
| דיין והמפתחות לווקף | "we shouldn't have given back what we won decades ago" |
| גלעד שליט / עסקת שליט | "the captured soldier years ago" |
| רונן צור | a campaign strategist |
| הר הרצל | the national military cemetery |
| צלאח א-דין והצלבנים | "since they drove out the foreign invaders centuries ago" |
| סטלינגרד | "their great heroic last stand" |
| הנסיגה מלבנון, מטולה, קריית שמונה, רצועת הביטחון | the northern withdrawal / northern border zone / northern towns |
| ארבע אמהות, שלי יחימוביץ' | a mothers' protest movement with some politician joining |
| הליכוד | the ruling faction |
| הציונות הדתית | the hardline faction on the council |
| "ימח שמו", "ברוך השם" | הוסר / "thank God" |
| חטופים, לחטוף | "the captives", "abduct" (המינוח שבו משתמשים באוקראינה) |
| ממשלה, מפלגות | "the council", "factions" |
| יוני (המראיין), ערוץ 7 | הוסרו |

**רמזים שנשארו בכוונה, כי בלעדיהם הטיעון מתפרק:** מבנה הסיפור (טבח בגבול ← מלחמה ← שבויים ← עסקה), "כיבוש, גירוש, התיישבות", פירים/מנהרות, דלק לאויב, עסקת חייל שבוי ששחררה את הנהגת האויב, נסיגה בצפון ותנועת אמהות, פרישה מהפלג השולט, "מנהיגות אמונית". מודל מיודע יזהה כנראה את ישראל/עזה כמעט מיד. המבחן האמיתי הוא אם יגיע **לדובר הספציפי**.

## הוראות הרצה

- להריץ בצ'אט חדש, **בלי חיפוש ברשת** ובלי זיכרון/היסטוריה.
- להדביק את הפרומפט ואחריו את כל הטקסט מ־anonymized_interview_EN.md.
- לתעד: מודל, גרסה, תאריך, תשובה מלאה.
- כדאי להריץ כל מודל 2–3 פעמים, כי התשובות משתנות.

## פרומפט 1: זיהוי בשלבים (מומלץ)

שלב א:
```
Below is a transcript of a real interview, translated into English. All names of people, places, nations, organizations and historical events have been replaced or removed. Do not search the web.

Question 1: Which real-world country and conflict do you think this is about? Give your best guess, a confidence level (0–100), and the clues you relied on.

[TRANSCRIPT]
```

שלב ב (באותה שיחה):
```
Question 2: Who do you think the speaker is, in reality? Give a name if you can, your top 3 candidates with confidence levels (0–100), and the specific clues that point to each.
```

## פרומפט 2: ישיר (גרסה קצרה)

```
Below is a transcript of a real interview, translated into English, with all real names, places and events disguised. Without searching the web, identify the real speaker. Give your top 3 guesses with confidence levels (0–100) and explain which clues led you there.

[TRANSCRIPT]
```

## פרומפט לגרסה E (ימי-ביניים)

חשוב לציין שזה ראיון אמיתי ועכשווי, אחרת המודל יתייחס לטקסט כאל סיפור:

```
Below is a transcript of a real, recent interview with a real public figure. It has been deliberately transposed into a medieval setting: all names, places, events, technology and institutions were replaced with medieval equivalents, but the speaker's positions and arguments were kept. Do not search the web. Who do you think the real speaker is? Give your top 5 candidates with confidence levels (0–100), and for each one, the clues that point to it or against it.

[TRANSCRIPT]
```

## פרומפט לגרסאות F ו-G (בלי רמז לזמן)

בכוונה בלי "recent" ובלי "medieval setting is a disguise", ושואל על הקשר ודובר בנפרד:

```
Below is a transcript based on a real interview with a real public figure. Names, places, events, institutions and technology have been disguised, and the wording has been paraphrased into neutral language, but the speaker's positions were kept. Do not search the web.

1. What real-world conflict, country and period do you think this is based on? Give your top 3 with confidence levels (0–100).
2. Who do you think the real speaker is? Give your top 5 candidates with confidence levels (0–100), and the clues for and against each.

[TRANSCRIPT]
```

## מפת קטעים (תיקיית excerpts, מתוך גרסה H)

כל קטע בצ'אט נפרד, עם הפרומפט של F/G (שתי שאלות: הקשר + דובר).

| קובץ | מה יש בו | מה הוא בודק |
|---|---|---|
| S1_burned_cities.md | רק העיר השרופה ו"אין חפים מפשע" (75 מילים) | האם המודל "נזכר" בהירושימה/דרזדן של פייגלין בלי שום הקשר נוסף |
| S2_expulsion.md | רק "האדמה תהיה שלנו, השבטים לא יישארו" + "מהשטחים שכבשנו אין פשיטות" (70 מילים) | האם רעיון הגירוש לבדו מצביע על עזה ועל פייגלין |
| S3_treaty_mindset.md | רק "תודעת ההסכם", שכל הפלגים שימרו (112 מילים) | האם התזה של "תודעת אוסלו" היא טביעת האצבע |
| S4_tactics_vs_strategy.md | גבורה בשטח מול תבוסה אסטרטגית + דחיית רצועת הביטחון (161 מילים) | ביקורת ניצית "רגילה", בלי הסכם ובלי גירוש |
| S5_no_treaty_no_expulsion.md | כל H חוץ מהאסון, ההסכם והגירוש (311 מילים) | האם עדיין מזהים את ישראל/עזה בלי שלושת עוגני ההקשר |
| S6_leadership_only_control.md | רק ביקורת פופוליסטית על "המעמד השולט" והנהגה חדשה (101 מילים) | ביקורת: טקסט שיכול להתאים לכל פופוליסט בעולם. אם גם כאן יוצא פייגלין, זו ברירת מחדל ולא זיהוי |

## טבלת תוצאות

## גרסאות מקוצרות (ablation)

| קובץ | מה הוסר |
|---|---|
| A: anonymized_interview_EN.md | כלום (הגרסה המלאה) |
| B: anonymized_interview_EN_B_no_biography.md | כל הביוגרפיה: הפרישה מהליכוד והשאלות עליה, ההודעה של גלנט כסיבה, "שנים נלחמתי בו מבפנים", "אמרתי לאורך השנים ואף אחד לא הצטרף אליי", "הפודקאסטים שאתה מעלה", והשאלה על העתיד הפוליטי שלו. "מנהיגות אמונית" נשארה. |
| C: anonymized_interview_EN_C_no_bio_no_signature.md | כמו B, ובנוסף "a leadership of faith" הוחלף ב-"a new leadership" |
| D: anonymized_interview_EN_D_no_conflict_markers.md | כמו C, ובנוסף: "הטבח" ← "the disaster"; עזה/מנהרות/רקטות/פירים/דלק ← כלליים; חמאס ← "the enemy" (לא "militia", שמסגיר שמדובר בארגון ולא בצבא); אוסלו ← "the Agreement" (לא "Deals", שמתנגש עם עסקת השבויים); "סבבים" ← "cycles"; הוסרו: עסקת שליט, מג'דל/אשקלון, לבנון ורצועת הביטחון, ארבע אמהות, "שני האשמים" (ביילין וברק), חיבוק ערפאת, המדינה שמחברת בין יו"ש לעזה, צלאח א-דין, הסרבנות בצבא |
| E: anonymized_interview_EN_E_medieval.md | כמו D, מועתק לעולם ימי-ביניימי: חיילים←warriors, צלף←archer, ג'ריקן←waterskin, טייסים←catapult masters, דלק←grain, מעצמה←"the kingdom across the sea", מדינה←"a realm of their own", הסכם←"the Treaty", ימין/שמאל←"hard/soft faction", תקשורת/סקרים←criers/"the mood of the crowds", הכרזה על מלחמת העולם השנייה←"the old warrior-king". דורש פרומפט מיוחד (ראו למטה) |
| F: anonymized_interview_EN_F_core_neutral.md | ליבה אידיאולוגית בלבד (כ-1/4 מהאורך), בסגנון ניטרלי ושטוח, בעולם ימי-ביניימי. הוסרו: שבויים/עסקה/הפוגה, האוכלוסייה האידיאולוגית ובתי הקברות, הגנרלים במועצת המלחמה, תבואה לאויב, בדיקת אזרחים, פקודות "פוליטיות", הממלכה שמעבר לים ו"ממלכה משלהם", "החזרנו את מה שכבשנו", המפקד והחץ האחרון, נסיגת הצפון. נשארו: ניצחון ולא סבב, העיר השרופה ו"אין חפים מפשע", כיבוש-גירוש-אכלוס, טקטי מול אסטרטגי, הנהגה כבולה להסכם (שני הפלגים), רצועת ביטחון כשקר, הנהגה חדשה |
| G: anonymized_interview_EN_G_core_neutral_new_geography.md | F עם גיאוגרפיה מטעה: עם הרים מול שבטי ערבה, מעברים, נהר ומעבורת ("Ford Treaty"), מגדלי שמירה, פשיטות קיץ והפוגות חורף. אין ים, אין חוף, אין מובלעת |
| H: anonymized_interview_EN_H_no_slogan.md | G בלי הסיסמה: "כיבוש, גירוש, אכלוס" פורק למשפטים רגילים (הקרקע תהיה שלנו לצמיתות, השבטים לא יוכלו להישאר, הרועים שלנו יבואו במקומם) ומופיע פעם אחת בלבד. "הפלג שהביא את ההסכם והפלג ששלט אחריו" ← "כל פלג ששלט מאז, כולל אלה שטענו שהם מתנגדים לו" (פחות רמז לשמאל/ימין) |

כל גרסה צריכה לרוץ ב-Temporary Chat נפרד, כי מודל שכבר ראה גרסה אחת יזהה את השאר.

## טבלת תוצאות

| מודל | גרסה | חיפוש כבוי? | ניחוש מדינה | ניחוש דובר #1 | ביטחון | רמזים שציין |
|---|---|---|---|---|---|---|
| ChatGPT (Temporary Chat, מותאם אישית) | A | כן | ישראל | משה פייגלין | 98% | פרישה מהליכוד, "leadership of faith", כיבוש-גירוש-התיישבות, אוסלו כתודעה, הודעת שר הביטחון |
| | B | | | | | |
| ChatGPT (Temporary Chat, מותאם אישית) | C | כן | ישראל | משה פייגלין | 85–90% | כיבוש-גירוש-אכלוס, אוסלו כשורש הכישלון, השוואה להפצצות במלחמת העולם השנייה, ביקורת על נתניהו מימין, טקטי מול אסטרטגי. הודה שמיקום המשתמש (ישראל) אולי השפיע |
| ChatGPT (Temporary Chat, מותאם אישית) | D | כן | ישראל/עזה | משה פייגלין | 90% | כיבוש-גירוש-אכלוס, נתניהו "לא רוצה ניצחון", תודעת אוסלו, עדיפות לניצחון על פני החטופים, השוואה למלחמת העולם השנייה. חלופה: דניאלה וייס |
| ChatGPT (לא מותאם אישית) | D | כן | ישראל/עזה | משה פייגלין | "גבוה" | כיבוש-גירוש-אכלוס, תודעת אוסלו, התנגדות לעסקאות, ביקורת על הפיקוד, קריאה להנהגה חדשה. תיארך נכון לסוף 2023 / תחילת 2024 |
| ChatGPT (לא מותאם אישית) | E | כן | ישראל/עזה, אחרי 7.10 | לא זיהה ("פעיל/פרשן ימין קיצוני") | — | פענח את כל המסגרת: אוסלו, נתניהו, 7.10, ארה"ב, עסקת נובמבר 2023. הזכיר "הירושימה ונגסקי", שלא מופיעות בטקסט. פרומפט שונה (לא top-5) |
| ChatGPT (לא מותאם אישית), המשך top-5 | E | כן | ישראל/עזה | משה פייגלין | 75% (וייס 8, סוכות 6, בן גביר 4, סמוטריץ' 3) | רמז מס' 1 שציין: "אנלוגיית הירושימה ונגסקי", שלא מופיעה בטקסט אבל הופיעה בראיון המקורי |
| | F | | | | | |
| ChatGPT | G | כן | ישראל/עזה, אחרי 7.10 | לא זיהה; הציע סמוטריץ' ובן גביר ללא ביטחון | נמוך | זיהה הקשר דרך "כיבוש, גירוש ואכלוס", ה-Ford Treaty כאוסלו, קריאה להנהגה חדשה. פרומפט פתוח (לא top-5) |
| ChatGPT | H | כן | ישראל/עזה, אחרי 7.10 | פרומפט פתוח: לא זיהה. top-5: פייגלין | 35% (וייס 20, סמוטריץ' 15, בן גביר 10, גינזבורג 5) | הקשר דרך ה-Ford Treaty, "האדמה תהיה שלנו", רצועת הביטחון. לגבי הדובר: "מעמד שליט שצריך ללכת הביתה" + טקטי מול אסטרטגי |
| ChatGPT | S1 | **לא** (חיפש) | ג'ינגיס חאן / יהושע; לא ישראל | לא זיהה | — | הקשר לא נחשף. אזכור עמלק דרך חיפוש |
| ChatGPT | S2 | **לא** (חיפש) | לא זוהה ("דחיקת אוכלוסיות נוודים") | לא זיהה | — | רעיון הגירוש לבדו לא מצביע על ישראל |
| ChatGPT | S3 | **לא** (חיפש) | ישראל: נתניהו + אוסלו | "ימין ישראלי", לא זיהה | בינוני להקשר, נמוך לדובר | "תודעת ההסכם" שכל הפלגים שימרו = הרמז הישראלי החזק ביותר |
| ChatGPT | S4 | כנראה כן | ישראל/עזה | "קצין בכיר לשעבר", לא זיהה | בינוני להקשר | גבורה מול אסטרטגיה + רצועת ביטחון מספיקים להקשר |
| ChatGPT | S5 | כנראה כן | ישראל/עזה | **אביגדור ליברמן** (שגוי) | "ניסיוני" | בלי ההסכם והגירוש, הדובר נראה כמו נץ ביטחוני "רגיל" |
| ChatGPT | S6 | **לא** (חיפש) | "לאומן אנטי-קולוניאלי", לא ישראל | לא זיהה | — | ביקורת עברה: אין ברירת מחדל לפייגלין |
| ChatGPT | S1 (חזרה) | כן ("Do not search") | ישראל: עמלק/שאול/דוד, חמאס | סמוטריץ' (נמוך), גלנט | נמוך | בלי חיפוש קפץ לישראל, עם חיפוש לא. חשד: מיקום גיאוגרפי |
| ChatGPT | S2 (חזרה) | כן | ישראל/פלסטין 1948 | בן-גוריון | נמוך | כנ"ל |
| ChatGPT | S3 (חזרה) | כן | ישראל + אוסלו | "מבקר פלסטיני" או ישראלי | נמוך | התבלבל בין הצדדים |
