# הפרוטוקול

את הפרוטוקול החלטנו לעצב בצורה הבאה: הלקוח והשרת יחליפו ביניהם הודעות JSON שמתארות את הפקודה שהלקוח רוצה לבצע ואת התשובה של השרת. ההודעות עוברות כטקסט מעל TCP, וכל הודעה מסתיימת ב-`\n` כדי שיהיה ברור איפה היא נגמרת.

הלקוח שולח בקשה בפורמט הבא:

```json
{
  "action": "<ACTION_NAME>",
  "data": { ... }
}
```

והשרת עונה בפורמט הבא:

```json
{
  "status": "<SUCCESS / ERROR>",
  "data": { ... },
  "message": "<Error message if there exists one>"
}
```

כשהבקשה נכשלת השרת מחזיר `"status": "ERROR"`, `data` ריק, ובשדה `message` הסבר שאפשר להציג למשתמש:

```json
{"status": "ERROR", "data": {}, "message": "Wrong password"}
```

אחרי התחברות מוצלחת השרת זוכר איזה משתמש מחובר בחיבור הזה, ולכן בשאר הבקשות לא צריך לשלוח את מספר המשתמש. כל פעולה חוץ מ-`REGISTER` ו-`LOGIN` דורשת להיות מחובר, אחרת השרת מחזיר `ERROR`.

## פורמט השדות

- **סכומי כסף** נשלחים כמחרוזת עם בדיוק שתי ספרות אחרי הנקודה, למשל `"500.00"` או `"-12.50"`, גם בבקשות וגם בתשובות. סכום בבקשה חייב להיות חיובי ועם לכל היותר שתי ספרות אחרי הנקודה.
- **קוד זיהוי משתמש** (`user_id`, `target_id`) הוא מחרוזת של 10 תווים מתוך `A-Z0-9`, למשל `"AB12CD34EF"`.
- **מספרי הוראות קבע והלוואות** (`order_id`, `loan_id`) הם מספרים שלמים חיוביים.
- **תאריכים** נשלחים בפורמט `"YYYY-MM-DD"`, ו**זמנים** בפורמט `"YYYY-MM-DD HH:MM:SS"`, לפי הזמן המדומה של השרת.




## הפעולות

הפעולה `<ACTION_NAME>` יכולה להיות אחת מהפעולות הבאות. בכל פעולה מופיעה קודם הבקשה ואחריה התשובה במקרה של הצלחה.

- `REGISTER` – פתיחת משתמש חדש. שם המשתמש הוא 3 עד 20 תווים מתוך אותיות, ספרות ו-`_`, והסיסמה לפחות 4 תווים. השרת מחזיר את קוד הזיהוי של המשתמש (`user_id`), מחרוזת ייחודית של 10 תווים מתוך `A-Z0-9`. שם המשתמש לא חייב להיות ייחודי, ולכן ההתחברות מתבצעת לפי קוד הזיהוי. ההרשמה לא מחברת את המשתמש.
  ```json
  {"action": "REGISTER", "data": {"name": "User", "password": "1234"}}
  {"status": "SUCCESS", "data": {"user_id": "AB12CD34EF"}}
  ```
- `LOGIN` – התחברות. הלקוח שולח את שם המשתמש, קוד הזיהוי והסיסמה, והשרת בודק שהשם והסיסמה מתאימים למשתמש עם קוד הזיהוי הזה.
  ```json
  {"action": "LOGIN", "data": {"name": "User", "user_id": "AB12CD34EF", "password": "1234"}}
  {"status": "SUCCESS", "data": {}}
  ```
- `LOGOUT` – התנתקות. אחרי התשובה הלקוח סוגר את החיבור. גם סגירת החיבור בלי `LOGOUT` מנתקת את המשתמש.
  ```json
  {"action": "LOGOUT", "data": {}}
  {"status": "SUCCESS", "data": {}}
  ```
- `GET_BALANCE` – בדיקת יתרה.
  ```json
  {"action": "GET_BALANCE", "data": {}}
  {"status": "SUCCESS", "data": {"balance": "1500.50"}}
  ```
- `GET_HISTORY` – היסטוריית עו"ש, מהפעולה הישנה לחדשה. השדות `from_ts` ו-`to_ts` הם אופציונליים (זמן Unix בשניות, כולל הגבולות); אם הם חסרים או `null` מוחזרת כל ההיסטוריה.
  ```json
  {"action": "GET_HISTORY", "data": {"from_ts": null, "to_ts": null}}
  {"status": "SUCCESS", "data": {"history": [
    {"time": "2026-11-12 14:13:20", "type": "DEPOSIT", "counterparty": "CASH", "counterparty_name": "CASH",
     "amount": "500.00", "balance": "500.00", "note": ""},
    {"time": "2026-11-12 14:15:20", "type": "TRANSFER_OUT", "counterparty": "XY98ZW76VU", "counterparty_name": "Dana",
     "amount": "-100.00", "balance": "400.00", "note": ""}
  ]}}
  ```
  - `type` הוא אחד מ: `DEPOSIT`, `WITHDRAWAL`, `TRANSFER_IN`, `TRANSFER_OUT`, `CHARGE`, `LOAN`, `LOAN_REPAYMENT`, `OVERDRAFT_INTEREST`.
  - `counterparty` הוא קוד הזיהוי של הצד השני, `CASH` בהפקדה ומשיכה, או `BANK` בהלוואות ובריבית. `counterparty_name` הוא השם שמוצג.
  - `amount` הוא הסכום עם סימן (שלילי כשכסף יוצא), ו-`balance` היתרה אחרי הפעולה.
- `DEPOSIT` / `WITHDRAW` – הפקדה או משיכה של כסף. משיכה מותרת גם אם היתרה נהיית שלילית.
  ```json
  {"action": "DEPOSIT", "data": {"amount": "500.00"}}
  {"status": "SUCCESS", "data": {"new_balance": "500.00"}}
  ```
- `TRANSFER` – העברה בנקאית חד פעמית למשתמש אחר. אסור להעביר לעצמך או למשתמש שלא קיים. השרת מחזיר את היתרה החדשה של השולח.
  ```json
  {"action": "TRANSFER", "data": {"target_id": "XY98ZW76VU", "amount": "200.00"}}
  {"status": "SUCCESS", "data": {"new_balance": "300.00"}}
  ```
- `STANDING_ORDER` – יצירת הוראת קבע חודשית. התשלום הראשון מתבצע היום, ואחריו פעם בחודש באותו יום בחודש (בחודש שאין בו את היום הזה, התשלום מתבצע ביום האחרון של החודש). `payments_limit` הוא מספר התשלומים; אם הוא `null` ההוראה פועלת עד שמבטלים אותה. השרת מחזיר את מספר ההוראה.
  ```json
  {"action": "STANDING_ORDER", "data": {"target_id": "XY98ZW76VU", "amount": "100.00", "payments_limit": 5}}
  {"status": "SUCCESS", "data": {"order_id": 1}}
  ```
- `GET_STANDING_ORDERS` – הצגת הוראות הקבע הפעילות שהמשתמש משלם (לא אלה שהוא מקבל). `executed` הוא מספר התשלומים שכבר בוצעו, `remaining` מספר התשלומים שנשארו (`null` אם עד ביטול), ו-`next_run` תאריך התשלום הבא.
  ```json
  {"action": "GET_STANDING_ORDERS", "data": {}}
  {"status": "SUCCESS", "data": {"orders": [
    {"order_id": 1, "target_id": "XY98ZW76VU", "target_name": "Dana", "amount": "100.00",
     "executed": 1, "remaining": 4, "next_run": "2026-12-12"}
  ]}}
  ```
- `CANCEL_STANDING_ORDER` – ביטול הוראת קבע. אפשר לבטל רק הוראה שהמשתמש משלם.
  ```json
  {"action": "CANCEL_STANDING_ORDER", "data": {"order_id": 1}}
  {"status": "SUCCESS", "data": {}}
  ```
- `TAKE_LOAN` – לקיחת הלוואה. השרת מאשר רק אם הלקוח לא במינוס. הסכום נכנס לחשבון מיד, ונגבה אוטומטית אחרי 30 יום עם ריבית של 5%. השרת מחזיר את מספר ההלוואה ואת היתרה החדשה.
  ```json
  {"action": "TAKE_LOAN", "data": {"amount": "5000.00"}}
  {"status": "SUCCESS", "data": {"loan_id": 1, "new_balance": "5500.00"}}
  ```
- `GET_LOANS` – הצגת כל ההלוואות של המשתמש. `repay_amount` הוא הסכום שייגבה (הקרן ועוד 5%), ו-`paid` אומר אם ההלוואה כבר נגבתה.
  ```json
  {"action": "GET_LOANS", "data": {}}
  {"status": "SUCCESS", "data": {"loans": [
    {"loan_id": 1, "principal": "5000.00", "repay_amount": "5250.00",
     "taken_on": "2026-11-12", "due_on": "2026-12-12", "paid": false}
  ]}}
  ```

## דוגמת ריצה

```
C -> S: {"action": "LOGIN", "data": {"name": "User", "user_id": "AB12CD34EF", "password": "abcd"}}
S -> C: {"status": "SUCCESS", "data": {}}
C -> S: {"action": "DEPOSIT", "data": {"amount": "1000.00"}}
S -> C: {"status": "SUCCESS", "data": {"new_balance": "1000.00"}}
C -> S: {"action": "WITHDRAW", "data": {"amount": "1500.00"}}
S -> C: {"status": "SUCCESS", "data": {"new_balance": "-500.00"}}
        (בשרת לוחצים Enter, עובר יום ונגבית ריבית של 0.05% על המינוס)
C -> S: {"action": "GET_BALANCE", "data": {}}
S -> C: {"status": "SUCCESS", "data": {"balance": "-500.25"}}
C -> S: {"action": "TAKE_LOAN", "data": {"amount": "1000.00"}}
S -> C: {"status": "ERROR", "data": {}, "message": "Loans are not allowed while the balance is negative"}
```

## הערות מימוש

השרת צריך לטפל בכמה לקוחות במקביל בלי לחסום את קידום הזמן, ולכן הוא משתמש ב-`console.poll` שקיבלנו עם התרגיל כדי לקרוא מה-stdin בלי לחסום. בכל פעם שעובר יום, השרת עובר על כל הלקוחות וגובה ריבית יומית של 0.05% ממי שנמצא במינוס.

בחרנו להעביר את ההודעות כ-JSON רגיל כדי שבחלק של ה-Wireshark יהיה אפשר לעשות Follow TCP Stream ולקרוא את ההודעות ישירות.

סכומי הכסף נשלחים כמחרוזות ולא כמספרים, כי מספר עשרוני (`float`) לא יכול לייצג בדיוק סכומים כמו `0.10`, וטעויות עיגול מצטברות בחישובי ריבית. השרת מחשב עם `Decimal` ומעגל לשתי ספרות.
