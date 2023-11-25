import asyncio
from datetime import datetime
from datetime import timedelta
import logging
import platform
import re

import aiohttp
import names
import websockets
from aiofile import async_open
from websockets import WebSocketServerProtocol, WebSocketProtocolError
from websockets.exceptions import ConnectionClosedOK

logging.basicConfig(level=logging.INFO)


class Server:
    clients = set()

    async def register(self, ws: WebSocketServerProtocol):
        """
        Registers a WebSocket connection.

        Parameters:
            - ws (WebSocketServerProtocol): The WebSocket connection to register.

        Returns:
            None

        This function sets a name for the WebSocket connection based on a generated full name,
        adds the connection to the set of clients, and logs the connection information.
        """

        ws.name = names.get_full_name()
        self.clients.add(ws)
        logging.info(f"{ws.remote_address} connects!")

    async def unregister(self, ws: WebSocketServerProtocol):
        """
        Unregisters a WebSocket connection.

        Parameters:
            - ws (WebSocketServerProtocol): The WebSocket connection to unregister.

        Returns:
            None

        This function removes the WebSocket connection from the set of clients and logs
        information about the disconnection.
        """

        self.clients.remove(ws)
        logging.info(f"{ws.remote_address} disconnects!")

    async def send_to_clients(self, message: str):
        """
        Sends a message to all registered WebSocket clients.

        Parameters:
            - message (str): The message to be sent to clients.

        Returns:
            None

        This function sends the specified message to all WebSocket clients registered
        with the WebSocket server. If there are no registered clients, the function does nothing.
        """

        if self.clients:
            [await client.send(message) for client in self.clients]

    async def handler(self, ws: WebSocketServerProtocol):
        """
        WebSocket connection handler.

        Parameters:
            - ws (WebSocketServerProtocol): The WebSocket connection.

        Returns:
            None

        This function registers the WebSocket connection, handles the distribution of messages,
        catches and logs any WebSocket protocol errors, and finally unregisters the WebSocket connection.
        """

        await self.register(ws)
        try:
            await self.distrubute(ws)
        except WebSocketProtocolError as err:
            logging.error(err)
        finally:
            await self.unregister(ws)

    async def distrubute(self, ws: WebSocketServerProtocol):
        """
        Distributes messages received from a WebSocket connection.

        Parameters:
            - ws (WebSocketServerProtocol): The WebSocket connection.

        Returns:
            None

        This function listens for messages from the WebSocket connection. If a message contains
        the keyword 'exchange', it extracts currency and date information, makes a request to obtain
        exchange rate data, processes the data, and sends the result to all clients. Otherwise, it
        sends the original message prefixed with the sender's name to all clients.
        """

        async for message in ws:
            if "exchange" in message.lower():
                async with async_open("info.txt", "a+") as log_file:
                    await log_file.write(f"{datetime.now()} - {ws.name}")

                currency, date = await self.parseTheString(message)
                date = await self.formatDate(date)

                jsonFile = await self.request(date)

                result = await self.currency_exchange(jsonFile, currency_name=currency)
                await self.send_to_clients(result)
            else:
                await self.send_to_clients(f"{ws.name}: {message}")

    async def formatDate(self, input_date: str):
        """
        Formats the input date and checks if it is within a valid range.

        Parameters:
            - input_date (str): The input date string in the format '%d.%m.%Y'.

        Returns:
            str or None: The formatted date if it is within the valid range,
            or None if the date is in an incorrect format or more than 10 days in the past.

        This function takes an input date string, attempts to parse it into a datetime object,
        and checks if the date is within 10 days from the current date. If the date is in the
        correct format and within the valid range, the formatted date is returned; otherwise, None
        is returned and an appropriate message is printed.
        """

        current_datetime = datetime.now()
        ten_days = timedelta(days=10)
        try:
            checked_date = datetime.strptime(input_date, "%d.%m.%Y")

            difference = current_datetime - checked_date
            if difference > ten_days:
                print(
                    "You cannot find out the exchange rate more than 10 days in advance"
                )
                return None
            return input_date
        except:
            print("Incorrect format of date")

    async def parseTheString(self, message: str):
        """
        Parses a message to extract currency and date information.

        Parameters:
            - message (str): The message to parse.

        Returns:
            tuple or None: A tuple containing currency and date if found in the message,
            or None if either currency or date is not found.

        This function uses regular expressions to search for a date pattern in the message
        and checks for the presence of specific currency codes. If both currency and date are
        found, a tuple with currency and date is returned; otherwise, None is returned and
        appropriate messages are printed.
        """

        pattern = r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"
        (matches,) = re.findall(pattern, message) or None

        list_of_currency = ["USD", "EUR", "PLZ", "AUD"]
        (currency,) = [elements for elements in list_of_currency if elements in message]
        # for elements in list_of_currency:
        #     if elements in message:
        #         currency = elements

        if matches == None:
            print("You haven't enter the date")
        elif currency == None:
            print("You haven't enter the currency")
        else:
            return (currency, matches)

    async def currency_exchange(self, response: dict, currency_name: str):
        """
        Extracts exchange rate information for a specific currency from a response dictionary.

        Parameters:
            - response (dict): The dictionary containing exchange rate information.
            - currency_name (str): The currency code for which to extract exchange rate information.

        Returns:
            str or None: A string containing buy and sale rates for the specified currency
            if information is found, or None if the exchange rate information is empty.

        This function takes a response dictionary containing exchange rate information
        and a currency code. It extracts and returns the buy and sale rates for the specified
        currency if information is found, or prints a message and returns None if the exchange
        rate information is empty.
        """

        exchangeRate = response.get("exchangeRate", [])
        if exchangeRate:
            (result,) = list(
                filter(
                    lambda element: element["currency"] == currency_name, exchangeRate
                )
            )
            return f"Currency: {currency_name}, buy: {result['purchaseRateNB']}, sale: {result['saleRateNB']}"
        else:
            print("Exchange Rate is empty")

    async def request(self, date):
        """
        Sends an asynchronous HTTP GET request to a specified URL.

        Parameters:
            - date (str): The date to include in the request URL.

        Returns:
            dict or None: A dictionary containing the JSON response if the request is successful,
            or None if there is an error or the response status is not 200.

        This function constructs a URL using the provided date, sends an asynchronous GET request to
        the URL using the aiohttp library, and returns the JSON response if the request is successful.
        If there is an error or the response status is not 200, an error message is printed, and None is returned.
        """

        url = f"https://api.privatbank.ua/p24api/exchange_rates?date={date}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        jsonFile = await response.json()
                        return jsonFile
                    else:
                        print(f"Error status: {response.status}")
            except aiohttp.ClientConnectionError as err:
                print(f"Connection error: {url}", str(err))


async def main():
    server = Server()
    async with websockets.serve(server.handler, "localhost", 8080):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    if platform.system == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
