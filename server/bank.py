"""In-memory bank: accounts, authentication, balances, transfers, history,
calendar-monthly standing orders and loans.

Designed for a single-threaded select()-based server: no locks. All timestamps
come from the bank's own ``SimTime`` clock. Due standing orders and loan
repayments are processed when the main loop calls ``run_due()`` (and after
the operator advances the bank date via ``on_console_line``).
"""
from __future__ import annotations

import logging
import random
from datetime import date, timedelta

from server_utils import SimTime

log = logging.getLogger("bank")

TOKEN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NAME_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"

LOAN_DAYS = 30
LOAN_INTEREST = 0.05
OVERDRAFT_DAILY_INTEREST = 0.0005  # 0.05% per day


def parse_amount(text):
    """Turn an amount string from the client ("100", "99.9", "99.90") into a float.
    Must be positive with at most 2 digits after the point."""
    if not isinstance(text, str):
        raise ValueError("Amount must be a string")
    parts = text.split(".")
    if len(parts) > 2 or not parts[0].isdigit():
        raise ValueError("Invalid amount")
    if len(parts) == 2 and (not parts[1].isdigit() or len(parts[1]) > 2):
        raise ValueError("Amount can have at most 2 digits after the point")
    amount = float(text)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return amount


def last_day_of_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def add_month(d, day):
    """Same day next month. If that month is too short, use its last day."""
    year, month = d.year, d.month + 1
    if month == 13:
        year, month = year + 1, 1
    return date(year, month, min(day, last_day_of_month(year, month)))


class Transaction:
    """One line in an account's history."""
    def __init__(self, ts, tx_type, counterparty, counterparty_name, amount, balance, note=""):
        self.ts = ts                    # simulated unix time
        self.tx_type = tx_type          # DEPOSIT / WITHDRAWAL / TRANSFER_IN / ...
        self.counterparty = counterparty  # other user's token, or CASH / BANK
        self.counterparty_name = counterparty_name
        self.amount = amount            # negative when money goes out
        self.balance = balance          # balance after this transaction
        self.note = note


class Account:
    def __init__(self, token, name, password):
        self.token = token
        self.name = name
        self.password = password
        self.balance = 0.0
        self.history = []

    def apply(self, amount, tx_type, counterparty, counterparty_name, ts, note=""):
        """Every change to the balance goes through here so the history stays correct."""
        self.balance = round(self.balance + amount, 2)
        self.history.append(Transaction(ts, tx_type, counterparty, counterparty_name,
                                        amount, self.balance, note))


class StandingOrder:
    def __init__(self, so_id, payer, payee, amount, count, start):
        self.so_id = so_id
        self.payer = payer
        self.payee = payee
        self.amount = amount
        self.count = count      # 0 means until cancelled
        self.day = start.day    # the day of the month it should run on
        self.next_run = start
        self.executed = 0
        self.active = True

    def remaining(self):
        if self.count == 0:
            return None
        return self.count - self.executed


class Loan:
    def __init__(self, loan_id, account, principal, taken_on):
        self.loan_id = loan_id
        self.account = account
        self.principal = principal
        self.repay_amount = round(principal * (1 + LOAN_INTEREST), 2)
        self.taken_on = taken_on
        self.due_on = taken_on + timedelta(days=LOAN_DAYS)
        self.paid = False


class Bank:
    def __init__(self, start_date: date):
        self.clock = SimTime(start_date=start_date)
        self.accounts = {}          # token -> Account
        self.standing_orders = {}   # so_id -> StandingOrder
        self.loans = []
        self.next_so_id = 1
        self.next_loan_id = 1

    def announce_date(self):
        print(f"Bank date: {self.clock.today()}  (press Enter to advance one day)", flush=True)

    # ---------- accounts ----------

    def new_token(self):
        while True:
            token = "".join(random.choice(TOKEN_CHARS) for _ in range(10))
            if token not in self.accounts:
                return token

    def register(self, name, password):
        if not isinstance(name, str) or not 3 <= len(name) <= 20:
            raise ValueError("Name must be 3-20 characters")
        for ch in name:
            if ch not in NAME_CHARS:
                raise ValueError("Name can only contain letters, digits and _")
        if not isinstance(password, str) or len(password) < 4:
            raise ValueError("Password must be at least 4 characters")

        token = self.new_token()
        self.accounts[token] = Account(token, name, password)
        log.info("new account %s (%s)", token, name)
        return token

    def get_account(self, token):
        if token not in self.accounts:
            raise ValueError("No such user")
        return self.accounts[token]

    def login(self, token, password):
        account = self.accounts.get(token)
        if account is None or account.password != password:
            raise ValueError("Wrong user id or password")
        return account.name

    # ---------- money ----------

    def deposit(self, token, amount):
        account = self.get_account(token)
        account.apply(amount, "DEPOSIT", "CASH", "CASH", self.clock.now())
        return account.balance

    def withdraw(self, token, amount):
        # going into minus is allowed, the bank charges daily interest for it
        account = self.get_account(token)
        account.apply(-amount, "WITHDRAWAL", "CASH", "CASH", self.clock.now())
        return account.balance

    def transfer(self, token, target, amount):
        sender = self.get_account(token)
        if target not in self.accounts:
            raise ValueError("Target user does not exist")
        if target == token:
            raise ValueError("Cannot transfer to yourself")
        receiver = self.accounts[target]

        now = self.clock.now()
        sender.apply(-amount, "TRANSFER_OUT", receiver.token, receiver.name, now)
        receiver.apply(amount, "TRANSFER_IN", sender.token, sender.name, now)
        return sender.balance

    def history(self, token, from_ts=None, to_ts=None):
        """History oldest first, optionally only between from_ts and to_ts (inclusive)."""
        result = []
        for t in self.get_account(token).history:
            if from_ts is not None and t.ts < from_ts:
                continue
            if to_ts is not None and t.ts > to_ts:
                continue
            result.append(t)
        return result

    # ---------- standing orders ----------

    def schedule_so(self, token, target, amount, count):
        payer = self.get_account(token)
        if target not in self.accounts:
            raise ValueError("Target user does not exist")
        if target == token:
            raise ValueError("Cannot make a standing order to yourself")
        if not isinstance(count, int) or count < 0:
            raise ValueError("Number of payments must be 0 or more")

        so = StandingOrder(self.next_so_id, payer, self.accounts[target], amount, count,
                           self.clock.today())
        self.next_so_id += 1
        self.standing_orders[so.so_id] = so
        self.pay_so(so)  # first payment happens today
        return so.so_id

    def pay_so(self, so):
        now = self.clock.now()
        note = f"Standing order #{so.so_id}"
        so.payer.apply(-so.amount, "CHARGE", so.payee.token, so.payee.name, now, note)
        so.payee.apply(so.amount, "TRANSFER_IN", so.payer.token, so.payer.name, now, note)
        so.executed += 1

        if so.count != 0 and so.executed >= so.count:
            so.active = False
        else:
            so.next_run = add_month(so.next_run, so.day)

    def get_so_list(self, token):
        account = self.get_account(token)
        return [so for so in self.standing_orders.values() if so.active and so.payer is account]

    def cancel_so(self, token, so_id):
        account = self.get_account(token)
        so = self.standing_orders.get(so_id)
        if so is None or so.payer is not account or not so.active:
            raise ValueError("No such standing order")
        so.active = False

    # ---------- loans ----------

    def take_loan(self, token, amount):
        account = self.get_account(token)
        if account.balance < 0:
            raise ValueError("Loans are not allowed while the balance is negative")

        loan = Loan(self.next_loan_id, account, amount, self.clock.today())
        self.next_loan_id += 1
        self.loans.append(loan)
        account.apply(amount, "LOAN", "BANK", "BANK", self.clock.now(), f"Loan #{loan.loan_id}")
        return loan.loan_id, account.balance

    def get_loans(self, token):
        account = self.get_account(token)
        return [loan for loan in self.loans if loan.account is account and not loan.paid]

    # ---------- time ----------

    def run_due(self):
        """Run every standing order and loan repayment whose date has come."""
        today = self.clock.today()

        for so in self.standing_orders.values():
            while so.active and so.next_run <= today:
                self.pay_so(so)

        for loan in self.loans:
            if not loan.paid and loan.due_on <= today:
                loan.account.apply(-loan.repay_amount, "LOAN_REPAYMENT", "BANK", "BANK",
                                   self.clock.now(), f"Loan #{loan.loan_id}")
                loan.paid = True

    def charge_overdraft_interest(self):
        """End of day: everyone in minus pays 0.05% of the minus."""
        for account in self.accounts.values():
            if account.balance < 0:
                interest = round(-account.balance * OVERDRAFT_DAILY_INTEREST, 2)
                if interest > 0:
                    account.apply(-interest, "OVERDRAFT_INTEREST", "BANK", "BANK", self.clock.now())

    def on_console_line(self, line):
        """Called by the console every time the operator presses Enter: move to the next day."""
        self.charge_overdraft_interest()
        self.clock.advance_day()
        self.run_due()
        self.announce_date()
