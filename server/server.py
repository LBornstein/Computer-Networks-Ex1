"""Single-threaded TCP banking server multiplexed with ``select()``.

Usage:
    python server.py [--host 127.0.0.1] [--port 5050] [--start-date YYYY-MM-DD] [--verbose]
"""
from __future__ import annotations

import socket
import select
import json
import argparse
import logging
from datetime import date

from bank import Bank, parse_amount
from server_utils import Console

log = logging.getLogger("server")

### Do not remove any of the existing functions or change their signatures. ###
### You can add new functions and classes if needed. ###
class Server:
    def __init__(self, host: str, port: int, bank: Bank):
        self.host = host
        self.port = port

        self.bank = bank
        self.bank.announce_date()
        
        self.console = Console()

    def server_loop(self) -> None:
        """Main server loop for the bank server."""

        #Initialize server listen.
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((self.host,self.port))
        server_socket.listen()
        server_socket.setblocking(False)

        sockets_list = [server_socket]
        self.clients = {}
        buffers = {}

        while True:
            read_sockets, _, exception_sockets = select.select(sockets_list, [], sockets_list, 0.1)

            for sock in read_sockets:
                if sock == server_socket:
                    client_sock, _ = server_socket.accept()
                    client_sock.setblocking(False)
                    sockets_list.append(client_sock)
                    self.clients[client_sock] = None
                    buffers[client_sock] = b""
                else:
                    try:
                        # Handle actual request
                        chunk = sock.recv(1024)
                        if not chunk:
                            sockets_list.remove(sock)
                            self.clients.pop(sock, None)
                            buffers.pop(sock, None)
                            sock.close()
                            continue
                        buffers[sock] += chunk
                        while b"\n" in buffers[sock]:
                            raw_line, buffers[sock] = buffers[sock].split(b"\n", 1)
                            if raw_line.strip():
                                self.handle_request(raw_line, sock)

                    except (ConnectionResetError, BrokenPipeError, OSError):
                        if sock in sockets_list:
                            sockets_list.remove(sock)
                        self.clients.pop(sock, None)
                        buffers.pop(sock, None)
                        sock.close()

            for sock in exception_sockets:
                if sock in sockets_list:
                    sockets_list.remove(sock)
                self.clients.pop(sock, None)
                buffers.pop(sock, None)
                sock.close()

            self.console.poll(self.bank.on_console_line)

    def parse_request(self, data: bytes) -> tuple[str, dict]:
        decoded = data.decode("utf-8").strip()
        request = json.loads(decoded)
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object")

        action = request.get("action")
        req_data = request.get("data")
        if not isinstance(action, str) or not isinstance(req_data, dict):
            raise ValueError("Invalid or missing 'action' or 'data'")

        return action, req_data

    def handle_request(self, data: bytes, client_sock: socket.socket) -> None:
        try:
            action, req_data = self.parse_request(data)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
            response = {
                "status": "ERROR",
                "data": {},
                "message": str(e),
            }
            client_sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
            return

        token = self.clients.get(client_sock)
        if action not in ("REGISTER", "LOGIN") and token is None:
            response = {
                "status": "ERROR",
                "data": {},
                "message": "User is not logged in",
            }
            client_sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
            return

        try:
            if action == "REGISTER":
                response = self.handle_register(req_data)
            elif action == "LOGIN":
                response = self.handle_login(req_data, client_sock)
            elif action == "LOGOUT":
                self.clients[client_sock] = None
                response = {"status": "SUCCESS", "data": {}}
            elif action == "GET_BALANCE":
                response = self.handle_get_balance(token)
            elif action == "HISTORY":
                response = self.handle_history(token, req_data)
            elif action == "DEPOSIT":
                response = self.handle_deposit(token, req_data)
            elif action == "WITHDRAW":
                response = self.handle_withdraw(token, req_data)
            elif action == "TRANSFER":
                response = self.handle_transfer(token, req_data)
            elif action == "SCHEDULE_SO":
                response = self.handle_schedule_so(token, req_data)
            elif action == "GET_SO_LIST":
                response = self.handle_get_so_list(token)
            elif action == "CANCEL_SO":
                response = self.handle_cancel_so(token, req_data)
            elif action == "LOAN":
                response = self.handle_loan(token, req_data)
            elif action == "GET_LOANS":
                response = self.handle_get_loans(token)
            else:
                response = {
                    "status": "ERROR",
                    "data": {},
                    "message": f"Unknown action: {action}",
                }
        except (ValueError, KeyError, TypeError) as e:
            response = {
                "status": "ERROR",
                "data": {},
                "message": str(e),
            }

        client_sock.sendall((json.dumps(response) + "\n").encode("utf-8"))

    # ---------- request handlers: each one returns the response dict ----------

    @staticmethod
    def ok(data=None):
        return {"status": "SUCCESS", "data": data if data is not None else {}}

    @staticmethod
    def money(x):
        return f"{x:.2f}"

    def handle_register(self, req_data):
        token = self.bank.register(req_data.get("user"), req_data.get("password"))
        return self.ok({"token": token})

    def handle_login(self, req_data, client_sock):
        token = req_data.get("token")
        name = self.bank.login(token, req_data.get("password"))
        self.clients[client_sock] = token  # remember who is logged in on this connection
        return self.ok({"user": name})

    def handle_get_balance(self, token):
        return self.ok({"balance": self.money(self.bank.get_account(token).balance)})

    def handle_history(self, token, req_data):
        from_ts = req_data.get("from_ts")
        to_ts = req_data.get("to_ts")
        for ts in (from_ts, to_ts):
            if ts is not None and not isinstance(ts, (int, float)):
                raise ValueError("from_ts / to_ts must be numbers or null")

        history = []
        for t in self.bank.history(token, from_ts, to_ts):
            history.append({
                "time": self.bank.clock.format(when=t.ts),
                "type": t.tx_type,
                "counterparty": t.counterparty,
                "counterparty_name": t.counterparty_name,
                "amount": self.money(t.amount),
                "balance": self.money(t.balance),
                "note": t.note,
            })
        return self.ok({"history": history})

    def handle_deposit(self, token, req_data):
        new_balance = self.bank.deposit(token, parse_amount(req_data.get("amount")))
        return self.ok({"new_balance": self.money(new_balance)})

    def handle_withdraw(self, token, req_data):
        new_balance = self.bank.withdraw(token, parse_amount(req_data.get("amount")))
        return self.ok({"new_balance": self.money(new_balance)})

    def handle_transfer(self, token, req_data):
        amount = parse_amount(req_data.get("amount"))
        new_balance = self.bank.transfer(token, req_data.get("target"), amount)
        return self.ok({"new_balance": self.money(new_balance)})

    def handle_schedule_so(self, token, req_data):
        amount = parse_amount(req_data.get("amount"))
        so_id = self.bank.schedule_so(token, req_data.get("target"), amount, req_data.get("count"))
        return self.ok({"so_id": so_id})

    def handle_get_so_list(self, token):
        so_list = []
        for so in self.bank.get_so_list(token):
            so_list.append({
                "so_id": so.so_id,
                "counterparty_token": so.payee.token,
                "counterparty_name": so.payee.name,
                "amount": self.money(so.amount),
                "executed": so.executed,
                "remaining": so.remaining(),
                "next_run": so.next_run.isoformat(),
            })
        return self.ok({"so_list": so_list})

    def handle_cancel_so(self, token, req_data):
        self.bank.cancel_so(token, req_data.get("so_id"))
        return self.ok()

    def handle_loan(self, token, req_data):
        loan_id, new_balance = self.bank.take_loan(token, parse_amount(req_data.get("amount")))
        return self.ok({"loan_id": loan_id, "new_balance": self.money(new_balance)})

    def handle_get_loans(self, token):
        loans = []
        for loan in self.bank.get_loans(token):
            loans.append({
                "loan_id": loan.loan_id,
                "principal": self.money(loan.principal),
                "repay_amount": self.money(loan.repay_amount),
                "taken_on": loan.taken_on.isoformat(),
                "due_on": loan.due_on.isoformat(),
            })
        return self.ok({"loans": loans})


### Do not touch anything below this line. ###
def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from None


def main() -> None:
    parser = argparse.ArgumentParser(description="select()-based socket banking server")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--start-date", type=parse_date, default=date.today(),
                        help="first bank date, YYYY-MM-DD (default: today)")
    parser.add_argument("--verbose", action="store_true", help="log every request and reply")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    bank = Bank(start_date=args.start_date)
    server = Server(args.host, args.port, bank)
    try:
        server.server_loop()
    except KeyboardInterrupt:
        log.info("shutting down")
        print("\nShutting down.", flush=True)


if __name__ == "__main__":
    main()
