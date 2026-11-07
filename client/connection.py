"""Network layer of the bank client.

Public methods return built-in Python values (str, int, list, tuple, None), except
history types which use the ``TxType`` enum so the GUI does not deal with raw
type strings. On a rejected or unexpected server reply they raise ``RequestFailed``
with a user-facing message. Transport failures raise ``ConnectionError`` / ``OSError``.
"""
from __future__ import annotations

import json
import socket

from enum import Enum
from typing import Callable, List, Optional, Tuple, Union


class TxType(Enum):
    """Finite set of history entry types the GUI understands.

    ``req_history`` returns these instead of free-form strings. The GUI turns
    them into display text; wire values from the server are mapped here.
    """

    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    CHARGE = "CHARGE"
    LOAN = "LOAN"
    LOAN_REPAYMENT = "LOAN_REPAYMENT"
    OVERDRAFT_INTEREST = "OVERDRAFT_INTEREST"

# --------------------------Error Classes --------------------------
# ---------Raise these for the GUI to react appropriately.----------
class ProtocolError(Exception):
    """The server sent something that cannot be parsed."""


class RequestFailed(Exception):
    """The server rejected the request. ``str(self)`` is safe to show to the user."""

### Do not remove any of the existing functions or change their signatures. ###
### You can add new functions and classes if needed. ###
class Connection:
    """One TCP connection to the bank server.

    Not thread-safe: call from a single thread (the GUI network worker, or a shell).
    """

    def __init__(self):
        self._sock = None       # the TCP socket; set to None while not connected
        self._recv_buf = b""    # bytes received after the last full message

    @property
    def connected(self) -> bool:
        """Returns True if a TCP connection to the server is currently open."""
        return self._sock is not None

    def connect(self, host: str, port: int) -> None:
        """Open a TCP connection to the bank server.

        Args:
            host: Server hostname or IP (e.g. ``\"127.0.0.1\"``).
            port: Server TCP port (e.g. ``5050``).
            timeout: Seconds to wait for the TCP handshake.

        Returns:
            None.

        Raises:
            OSError / ConnectionError: if the server cannot be reached.
        """
        self.close() #close at the start incase there is already an open connection
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._sock.connect((host, port))
        except OSError:
            self.close()  # connecting failed: free the socket so connected is False
            raise         # let the GUI see the error
        self._recv_buf = b"" #empty buffer

    def close(self) -> None:
        """Close the TCP connection if one is open. Safe to call more than once.

        Returns:
            None.
        """
        if self._sock is None:
            return
        try:
            self._sock.close()
        finally:
            self._sock = None
            self._recv_buf = b""

    def req_register(self, user: str, password: str) -> str:
        """Register a new account.

        Args:
            user: Account name (3-20 letters/digits/``_``). Need not be unique.
            password: Password (at least 4 characters).

        Returns:
            The new unique user id (token), a 10-character ``A-Z0-9`` string.

        Raises:
            RequestFailed: registration rejected (bad username/password, …).
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("REGISTER", {"user": user, "password": password})
        user_id = response.get("data", {}).get("token")
        if not isinstance(user_id, str) or not user_id:
            raise RequestFailed("Server did not return a user id.")
        return user_id

    def req_login(self, token: str, password: str) -> str:
        """Log in to an existing account on this connection.

        Args:
            token: User id (account id) issued at registration.
            password: Account password.

        Returns:
            The account name (username) for this user id.

        Raises:
            RequestFailed: wrong credentials / unknown user id.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("LOGIN", {"token": token, "password": password})
        name = response.get("data", {}).get("user")
        if not isinstance(name, str) or not name:
            raise RequestFailed("Server did not return the account name.")
        return name

    def req_logout(self) -> None:
        """Log out and close the connection.

        Returns:
            None.
        """
        try:
            self._send_and_receive("LOGOUT")
        finally:
            self.close()

    def req_get_balance(self) -> str:
        """Fetch the logged-in account's balance.

        Returns:
            Balance string with two decimals, e.g. ``\"500.00\"`` or ``\"-12.50\"``.

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("GET_BALANCE")
        balance = response.get("data", {}).get("balance")
        if not isinstance(balance, str) or not balance:
            raise RequestFailed("Server did not return a balance.")
        return balance

    def req_deposit(self, amount: str) -> str:
        """Deposit cash into the logged-in account.

        Args:
            amount: Positive decimal string, at most 2 fractional digits (e.g. ``\"99.90\"``).

        Returns:
            New balance string (two decimals).

        Raises:
            RequestFailed: invalid amount or not logged in.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("DEPOSIT", { "amount": amount})
        new_balance = response.get("data", {}).get("new_balance")
        if not isinstance(new_balance , str) or not new_balance :
            raise RequestFailed("Server did not return the new balance.")
        return new_balance 

    def req_withdraw(self, amount: str) -> str:
        """Withdraw cash from the logged-in account (may go negative).

        Args:
            amount: Positive decimal string, at most 2 fractional digits.

        Returns:
            New balance string (two decimals).

        Raises:
            RequestFailed: invalid amount or not logged in.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("WITHDRAW", { "amount": amount})
        new_balance = response.get("data", {}).get("new_balance")
        if not isinstance(new_balance , str) or not new_balance :
            raise RequestFailed("Server did not return the new balance.")
        return new_balance 


    def req_transfer(self, target: str, amount: str) -> str:
        """Transfer money to another account.

        Args:
            target: Recipient user id (token).
            amount: Positive decimal string, at most 2 fractional digits.

        Returns:
            New balance of the sender (two decimals).

        Raises:
            RequestFailed: bad amount, unknown target, self-transfer, …
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("TRANSFER", {"target": target, "amount": amount})
        new_balance = response.get("data", {}).get("new_balance")
        if not isinstance(new_balance , str) or not new_balance :
            raise RequestFailed("Server did not return the new balance.")
        return new_balance


    def req_schedule_so(self, target: str, amount: str, count: str) -> int:
        """Create a monthly standing order (first payment today).

        Args:
            target: Payee user id (token).
            amount: Amount per payment (positive decimal string).
            count: Number of payments as a digit string; ``\"0\"`` means until cancelled.

        Returns:
            The new standing-order id (positive int).

        Raises:
            RequestFailed: validation error or unknown target.
            ConnectionError: connection lost.
        """
        try:
            count = int(count)
        except (ValueError, TypeError):
            raise RequestFailed("Invalid number of payments.")
        response = self._send_and_receive("SCHEDULE_SO", {"target": target , "amount": amount , "count": count})
        so_id = response.get("data", {}).get("so_id")
        if not isinstance(so_id , int) or not so_id :
            raise RequestFailed("Server did not return the standing order id.")
        return so_id 


    def req_get_so_list(self) -> List[Tuple[int, str, str, str, int, Optional[int], str]]:
        """List active standing orders paid by the logged-in account.

        Returns:
            A list of tuples, one per standing order, in any order::

                (so_id, counterparty_token, counterparty_name,
                 amount, executed, remaining, next_run)

            * ``so_id`` (int)
            * ``counterparty_token`` (str) — payee user id
            * ``counterparty_name`` (str) — payee account name
            * ``amount`` (str) — per-payment amount, two decimals
            * ``executed`` (int) — how many payments have run
            * ``remaining`` (int | None) — payments left, or ``None`` if until cancelled
            * ``next_run`` (str) — next payment date ``YYYY-MM-DD``

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("GET_SO_LIST")
        items = response.get("data", {}).get("so_list", [])
        if not isinstance(items, list):
            raise ProtocolError("Server did not return a standing order list.")

        result = []
        try:
            for so in items:
                result.append((so["so_id"], so["counterparty_token"], so["counterparty_name"],
                               so["amount"], so["executed"], so["remaining"], so["next_run"]))
        except (KeyError, TypeError):
            raise ProtocolError("Bad standing order in server reply.")
        return result

    def req_cancel_so(self, so_id: Union[str, int]) -> None:
        """Cancel one of the logged-in account's standing orders.

        Args:
            so_id: Standing-order id (int or digit string).

        Returns:
            None on success.

        Raises:
            RequestFailed: unknown standing order or not owned by this account.
            ConnectionError: connection lost.
        """
        try:
            so_id = int(so_id)
        except (ValueError, TypeError):
            raise RequestFailed("Invalid standing order id.")
        self._send_and_receive("CANCEL_SO", {"so_id": so_id})

    def req_loan(self, amount: str) -> Tuple[int, str]:
        """Take a loan (principal credited now; auto-repay after 30 bank days + 5%).

        Args:
            amount: Principal as a positive decimal string.

        Returns:
            ``(loan_id, new_balance)`` where ``loan_id`` is int and ``new_balance``
            is a two-decimal string.

        Raises:
            RequestFailed: invalid amount or not logged in.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("LOAN", {"amount": amount})
        data = response.get("data", {})
        loan_id = data.get("loan_id")
        new_balance = data.get("new_balance")
        if not isinstance(loan_id, int) or not isinstance(new_balance, str) or not new_balance:
            raise ProtocolError("Server did not return the loan id and new balance.")
        return (loan_id, new_balance)

    def req_get_loans(self) -> List[Tuple[int, str, str, str, str]]:
        """List unpaid loans for the logged-in account.

        Returns:
            A list of tuples, one per unpaid loan, in any order::

                (loan_id, principal, repay_amount, taken_on, due_on)

            * ``loan_id`` (int)
            * ``principal`` (str) — two decimals
            * ``repay_amount`` (str) — principal * 1.05, two decimals
            * ``taken_on`` (str) — ``YYYY-MM-DD``
            * ``due_on`` (str) — ``YYYY-MM-DD``

        Raises:
            RequestFailed: not logged in or server error.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("GET_LOANS")
        items = response.get("data", {}).get("loans", [])
        if not isinstance(items, list):
            raise ProtocolError("Server did not return a loans list.")

        result = []
        try:
            for item in items:
                result.append((item["loan_id"], item["principal"], item["repay_amount"], item["taken_on"], item["due_on"]))
        except (KeyError, TypeError):
            raise ProtocolError("Bad loan in server reply.")
        return result


    def req_history(self, from_ts: Optional[float] = None,
                    to_ts: Optional[float] = None) -> List[Tuple[str, TxType, str, str, str, str, str]]:
        """Fetch account history (oldest first). The GUI reverses for display.

        Args:
            from_ts: Optional inclusive lower bound (Unix seconds). The GUI passes
                neither bound (full history).
            to_ts: Optional inclusive upper bound (Unix seconds).

        Returns:
            A list of tuples, **oldest first**::

                (time, type, counterparty, counterparty_name, amount, balance, note)

            * ``time`` (str) — e.g. ``\"2026-10-30 14:13:20\"``
            * ``type`` (``TxType``) — e.g. ``TxType.DEPOSIT``, ``TxType.TRANSFER_IN``, …
            * ``counterparty`` (str) — other party token, ``CASH``, or ``BANK``
            * ``counterparty_name`` (str) — display name (may equal counterparty)
            * ``amount`` (str) — signed two-decimal amount for this entry
            * ``balance`` (str) — balance after this entry, two decimals
            * ``note`` (str) — free text (may be empty)

        Raises:
            RequestFailed: not logged in or bad timestamps.
            ConnectionError: connection lost.
        """
        response = self._send_and_receive("HISTORY", {"from_ts": from_ts, "to_ts": to_ts})
        items = response.get("data", {}).get("history", [])
        if not isinstance(items, list):
            raise ProtocolError("Server did not return a history list.")

        result = []
        try:
            for item in items:
                result.append((item["time"], TxType(item["type"]), item["counterparty"],
                               item["counterparty_name"], item["amount"], item["balance"], item["note"]))
        except (KeyError, TypeError, ValueError):
            raise ProtocolError("Bad history entry in server reply.")
        return result


    #Additional functions here:
    @staticmethod
    def build_request(action, data=None):
        """Build a protocol request and return it as bytes (newline-terminated)."""
        request = {
            "action": action,
            "data": data if data is not None else {}
        }
        return (json.dumps(request) + "\n").encode("utf-8")

    def _send_msg(self, sock, msg: bytes) -> None:
        """Send the whole message using send() in a loop.

        send() may send only part of the bytes, so we keep sending the rest
        until everything went out.
        """
        total_sent = 0
        while total_sent < len(msg):
            sent = sock.send(msg[total_sent:])
            if sent == 0:
                raise ConnectionError("Connection to the server was lost.")
            total_sent += sent

    def _recv_msg(self, sock) -> bytes:
        """Receive one protocol message (everything up to the ``\\n``).

        TCP is a stream, so one recv() may return half a message or more than one.
        We concatenate recv() results into a buffer until a full line arrived,
        and keep the leftover bytes for next time.
        """
        while b"\n" not in self._recv_buf:
            data = sock.recv(1024)
            if data == b"":  # empty bytes => the server closed the connection
                raise ConnectionError("Server closed the connection.")
            self._recv_buf += data
        msg, self._recv_buf = self._recv_buf.split(b"\n", 1)
        return msg

    def _send_and_receive(self, action, data=None) -> dict:
        """Send one request and return the parsed SUCCESS response.

        Raises:
            ConnectionError: not connected, or the connection failed.
            ProtocolError: the reply is not a valid protocol message.
            RequestFailed: the server answered with status ERROR.
        """
        if not self.connected:
            raise ConnectionError("Not connected to the server.")
        sock = self._sock

        try:
            self._send_msg(sock, self.build_request(action, data))
            msg = self._recv_msg(sock)
        except ConnectionError:
            raise
        except OSError as e:  # every socket function raises OSError on failure
            raise ConnectionError(f"Connection error: {e}") from e

        try:
            response = json.loads(msg.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ProtocolError(f"Invalid response from server: {e}") from e
        if not isinstance(response, dict) or "status" not in response:
            raise ProtocolError("Response is missing a status field.")

        if response["status"] != "SUCCESS":
            raise RequestFailed(response.get("message") or "Request failed.")
        if not isinstance(response.get("data", {}), dict):
            raise ProtocolError("Response data is not an object.")
        return response
