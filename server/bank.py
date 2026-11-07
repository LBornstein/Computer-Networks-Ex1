"""In-memory bank: accounts, authentication, balances, transfers, history,
calendar-monthly standing orders and loans.

Designed for a single-threaded select()-based server: no locks. All timestamps
come from the bank's own ``SimTime`` clock. Due standing orders and loan
repayments are processed when the main loop calls ``run_due()`` (and after
the operator advances the bank date via ``on_console_line``).
"""
from __future__ import annotations

import logging
from datetime import date

from server_utils import SimTime

log = logging.getLogger("bank")

class Bank:
    def __init__(self, start_date: date):
        self.clock = SimTime(start_date=start_date)
        self.clients = {}
        self.num_clients = 0

    def add_client(self, account_name, password):
        self.num_clients += 1
        account_id = self.num_clients
        client = Client(account_name, password)
        self.clients[account_id] = client
        return account_id

    def login(self, account_id, password):
        return self.clients[account_id].password == password

    def deposit(self, account_id, amount):
        client = self.clients[account_id]
        client.balance += amount
        t = Transaction(self.clients[account_id].account_name, self.clients[account_id].account_name, self.clock.now(), "Deposit")
        self.clients[account_id].transactions.append(t)

    def withdraw(self, account_id, amount):
        client = self.clients[account_id]
        client.balance -= amount
        t = Transaction(self.clients[account_id].account_name, self.clients[account_id].account_name, self.clock.now(), "Withdraw")
        self.clients[account_id].transactions.append(t)
        

    def transfer(self, sender_account_id, reciever_account_id, amount):
        self.withdraw(sender_account_id, amount)
        self.deposit(reciever_account_id, amount)
        t = Transaction(self.clients[sender_account_id].account_name, self.clients[reciever_account_id].account_name, self.clock.now(), "Transfer")
        self.clients[sender_account_id].transactions.append(t)
        self.clients[reciever_account_id].transactions.append(t)
    

#add the rest of the needed actions

class Client:
    def __init__(self, account_name, password):
        self.account_name = account_name
        self.password = password
        self.balance = 0
        self.transactions = []
        self.standing_orders = []
        self.loans = []


class Transaction:
    def __init__(self, sender, reciever, time, reason):
        self.sender = sender
        self.reciever = reciever
        self.time = time
        self.reason = reason