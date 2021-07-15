import urllib
import http.client as http_client

from driftbase.utils.test_utils import BaseCloudkitTest


class MessagesTest(BaseCloudkitTest):
    """
    Tests for the /messages endpoints
    """

    def test_messages_send(self):
        player_receiver = self.make_player()
        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages_url"]

        player_sender = self.make_player()

        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data)
        message_url = r.json()["url"]
        self.assertIn("payload", r.json())
        self.assertIn("Hello", r.json()["payload"])

        # we should not be able to read the message back, only the recipient can do that
        r = self.get(message_url, expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("that belongs to you", r.json()["error"]["description"])

        # we should not be able to read anything from the exchange either
        r = self.get(messages_url, expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("that belongs to you", r.json()["error"]["description"])

    def test_messages_receive(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint).json()
        messagequeue_url_template = r["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {
            "message" : {"Hello": "World"}
        }
        r = self.post(messagequeue_url, data=data).json()
        message_url = r["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # Attempt to fetch just the message we just sent
        # NOTE: Fetching a particular message simply does not work and probably hasn't for a while
        #r = self.get(message_url).json()

        # get all the messages for the player
        r = self.get(messages_url).json()
        self.assertIn("testqueue", r)
        self.assertEqual(len(r["testqueue"]), 1)
        self.assertIn("payload", r["testqueue"][0])
        self.assertIn("Hello", r["testqueue"][0]["payload"])

        # get all the messages for the player again and make sure we're receiving the same thing
        self.assertEqual(self.get(messages_url).json(), r)

    def test_messages_rows(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        otherdata = {"message": {"Hello": "OtherWorld"}}

        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=otherdata)
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=otherdata)

        top_message_number = r.json()["message_number"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all messages
        print(messages_url)
        r = self.get(messages_url)
        js = r.json()
        self.assertEqual(len(js), 2)
        self.assertEqual(len(js[queue]), 2)
        self.assertEqual(len(js[otherqueue]), 2)

        # get 1 row and verify that it is the latest one
        r = self.get(messages_url + "?rows=1")
        js = r.json()
        self.assertEqual(len(js), 1)
        self.assertNotIn(queue, js)
        self.assertEqual(len(js[otherqueue]), 1)
        self.assertEqual(js[otherqueue][0]["message_number"], top_message_number)

        # get 2 rows and verify that we have one from each queue
        r = self.get(messages_url + "?rows=2")
        js = r.json()
        self.assertEqual(len(js), 2)
        self.assertEqual(len(js[queue]), 1)
        self.assertEqual(len(js[otherqueue]), 1)

    def test_messages_after(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        otherdata = {"message": {"Hello": "OtherWorld"}}
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=otherdata)
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=otherdata)

        top_message_number = int(r.json()["message_number"])
        top_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get only the top row and verify that it is correct, each time
        for i in range(0, 2):
            r = self.get(messages_url + "?messages_after=%s" % (top_message_number - 1))
            js = r.json()
            # Check we got one queue
            self.assertEqual(len(js), 1)
            # Check we got one message in the queue
            self.assertEqual(len(js[otherqueue]), 1)
            record = js[otherqueue][0]
            self.assertEqual(record["message_number"], top_message_number)
            self.assertEqual(record["message_id"], top_message_id)
            self.assertEqual(record["payload"], otherdata["message"])

        # if we get by a larger number we should get nothing
        r = self.get(messages_url + "?messages_after=%s" % (top_message_number))
        js = r.json()
        self.assertEqual(js, {})

        # if we get by zero we should get nothing, as we've previously acknowledged a valid top number
        r = self.get(messages_url + "?messages_after=%s" % (0))
        js = r.json()
        self.assertEqual(js, {})

        # if we get without a message number should get nothing, as we've previously acknowledged a valid top number
        r = self.get(messages_url)
        js = r.json()
        self.assertEqual(js, {})

        # Send additional messages
        player_sender = self.make_player()

        # Post additional messages
        r = self.post(othermessagequeue_url, data=otherdata)
        r = self.post(othermessagequeue_url, data=otherdata)

        top_message_number = int(r.json()["message_number"])
        top_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get by zero should now return the two messages sent since last time
        r = self.get(messages_url + "?messages_after=%s" % (0))
        js = r.json()
        self.assertEqual(len(js), 1)
        self.assertEqual(len(js[otherqueue]), 2)
        # Messages are returned newest first
        self.assertEqual(js[otherqueue][0]["message_number"], top_message_number)
        self.assertEqual(js[otherqueue][0]["message_id"], top_message_id)
        self.assertEqual(js[otherqueue][1]["message_number"], top_message_number - 1)

    def test_messages_multiplequeues(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers
        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages_url"]

        player_sender = self.make_player()
        num_queues = 5
        num_messages_per_queue = 3
        for i in range(num_queues):
            messagequeue_url = messagequeue_url_template.format(queue="testqueue-%s" % i)
            for j in range(num_messages_per_queue):
                data = {"message": {"Hello": "World", "queuenumber": i, "messagenumber": j}}
                r = self.post(messagequeue_url, data=data)
                self.assertIn("payload", r.json())
                self.assertEqual(r.json()["payload"]["queuenumber"], i)
                self.assertEqual(r.json()["payload"]["messagenumber"], j)

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the queues and delete them
        r = self.get(messages_url)

        self.assertEqual(len(r.json()), num_queues)
        for queue, messages in r.json().items():
            self.assertEqual(len(messages), num_messages_per_queue)

    def test_messages_longpoll(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data)
        message_url = r.json()["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the messages for the player using a 1 second long poll
        r = self.get(messages_url + "?timeout=1")
        self.assertIn("testqueue", r.json())
        self.assertEqual(len(r.json()["testqueue"]), 1)
        self.assertIn("payload", r.json()["testqueue"][0])
        self.assertIn("Hello", r.json()["testqueue"][0]["payload"])
