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

אחרי התחברות מוצלחת השרת זוכר איזה משתמש מחובר בחיבור הזה, ולכן בשאר הבקשות לא צריך לשלוח את מספר המשתמש.


## הפעולות

הפעולה `<ACTION_NAME>` יכולה להיות אחת מהפעולות הבאות:

- `REGISTER` – פתיחת משתמש חדש. השרת מחזיר את קוד הזיהוי של המשתמש.
  ```json
  {"action": "REGISTER", "data": {"name": "User", "password": "123"}}
  {"status": "SUCCESS", "data": {"user_id": "1001"}}
  ```
- `LOGIN` – התחברות.
  ```json
  {"action": "LOGIN", "data": {"user_id": "1001", "password": "123"}}
  {"status": "SUCCESS", "data": {"balance": 0}}
  ```
- `GET_BALANCE` – בדיקת יתרה.
  ```json
  {"action": "GET_BALANCE", "data": {}}
  {"status": "SUCCESS", "data": {"balance": 1500.5}}
  ```
- `GET_HISTORY` – היסטוריית עו"ש.
  ```json
  {"action": "GET_HISTORY", "data": {}}
  {"status": "SUCCESS", "data": {"history": [{"time": "Day 1", "amount": 500, "party": "Bank", "reason": "deposit"}]}}
  ```
- `DEPOSIT` / `WITHDRAW` – הפקדה או משיכה של כסף.
  ```json
  {"action": "DEPOSIT", "data": {"amount": 500}}
  {"status": "SUCCESS", "data": {"new_balance": 300}}
  ```
- `TRANSFER` – העברה בנקאית למשתמש אחר.
  ```json
  {"action": "TRANSFER", "data": {"target_id": "1002", "amount": 200}}
  ```
- `STANDING_ORDER` – יצירת הוראת קבע. אם `payments_limit` חסר או `null`, ההוראה פועלת עד שמבטלים אותה.
  ```json
  {"action": "STANDING_ORDER", "data": {"target_id": "1002", "amount": 100, "payments_limit": 5}}
  ```
- `GET_STANDING_ORDERS` / `CANCEL_STANDING_ORDER` – הצגה וביטול של הוראות קבע.
  ```json
  {"action": "GET_STANDING_ORDERS", "data": {}}
  {"action": "CANCEL_STANDING_ORDER", "data": {"order_id": "123"}}
  ```
- `TAKE_LOAN` – לקיחת הלוואה. השרת בודק שהלקוח לא במינוס ומאשר או דוחה. ההלוואה נגבית אוטומטית אחרי 30 יום עם ריבית של 5%.
  ```json
  {"action": "TAKE_LOAN", "data": {"amount": 5000}}
  ```
- `GET_LOANS` – הצגת ההלוואות של המשתמש.
  ```json
  {"action": "GET_LOANS", "data": {}}
  ```

## דוגמת ריצה

```
C -> S: {"action": "LOGIN", "data": {"user_id": "1001", "password": "abc"}}
S -> C: {"status": "SUCCESS", "data": {"balance": 0}}
C -> S: {"action": "DEPOSIT", "data": {"amount": 1000}}
S -> C: {"status": "SUCCESS", "data": {"new_balance": 1000}}
C -> S: {"action": "WITHDRAW", "data": {"amount": 1500}}
S -> C: {"status": "SUCCESS", "data": {"new_balance": -500}}
        (בשרת לוחצים Enter, עובר יום ונגבית ריבית של 0.05% על המינוס)
C -> S: {"action": "GET_BALANCE", "data": {}}
S -> C: {"status": "SUCCESS", "data": {"balance": -500.25}}
```

## הערות מימוש

השרת צריך לטפל בכמה לקוחות במקביל בלי לחסום את קידום הזמן, ולכן הוא משתמש ב-`console.poll` שקיבלנו עם התרגיל כדי לקרוא מה-stdin בלי לחסום. בכל פעם שעובר יום, השרת עובר על כל הלקוחות וגובה ריבית יומית של 0.05% ממי שנמצא במינוס.

בחרנו להעביר את ההודעות כ-JSON רגיל כדי שבחלק של ה-Wireshark יהיה אפשר לעשות Follow TCP Stream ולקרוא את ההודעות ישירות.
