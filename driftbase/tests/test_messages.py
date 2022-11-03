import datetime
import http.client
import urllib
from mock import patch

from driftbase.utils.test_utils import BaseCloudkitTest


class MessagesTest(BaseCloudkitTest):
    """
    Tests for the /messages endpoints
    """

    def make_player_message_endpoint_and_session(self):
        self.make_player()
        return self.endpoints["my_player"], self.headers

    def get_messages_url(self, player_receiver_endpoint):
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messagequeue_url_template = urllib.parse.unquote(messagequeue_url_template)
        messages_url = r.json()["messages_url"]
        return messagequeue_url_template, messages_url

    def test_messages_send(self):
        player_receiver_endpoint, _ = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        player_sender = self.make_player()

        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK).json()
        message_url = r["url"]
        self.assertIsInstance(r["message_id"], str)

        # we should not be able to read the message back, only the recipient can do that
        r = self.get(message_url, expected_status_code=http.client.BAD_REQUEST)
        self.assertIn("that belongs to you", r.json()["error"]["description"])

        # we should not be able to read anything from the exchange either
        r = self.get(messages_url, expected_status_code=http.client.BAD_REQUEST)
        self.assertIn("that belongs to you", r.json()["error"]["description"])

    def test_messages_receive(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {
            "message": {"Hello": "World"}
        }
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK).json()
        message_url = r["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # Attempt to fetch just the message we just sent
        r = self.get(message_url).json()
        self.assertEqual(r["queue"], "testqueue")
        self.assertIn("payload", r)
        self.assertIn("Hello", r["payload"])
        self.assertIsInstance(r["exchange_id"], int)

        # get all the messages for the player
        r = self.get(messages_url).json()
        self.assertIn("testqueue", r)
        self.assertEqual(len(r["testqueue"]), 1)
        message = r["testqueue"][0]
        self.assertIn("payload", message)
        self.assertIn("Hello", message["payload"])
        self.assertIsInstance(message["exchange"], str)
        self.assertIsInstance(message["exchange_id"], int)
        self.assertIsInstance(message["message_id"], str)
        self.assertIsInstance(message["message_number"], int)
        self.assertIsInstance(message["payload"], dict)
        self.assertIsInstance(message["queue"], str)
        self.assertIsInstance(message["sender_id"], int)

        # get all the messages for the player again and make sure we're receiving the same thing
        self.assertEqual(self.get(messages_url).json(), r)

    def test_messages_rows(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        otherdata = {"message": {"Hello": "OtherWorld"}}

        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)
        first_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.OK)
        second_message_id = r.json()["message_id"]
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)
        third_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.OK)
        last_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all messages
        r = self.get(messages_url)
        js = r.json()
        self.assertEqual(len(js), 2)
        self.assertEqual(len(js[queue]), 2)
        self.assertEqual(len(js[otherqueue]), 2)

        # get 1 row and verify that it is the last one
        r = self.get(messages_url + "?rows=1")
        js = r.json()
        self.assertEqual(len(js), 1)
        self.assertNotIn(queue, js)
        self.assertEqual(len(js[otherqueue]), 1)
        self.assertEqual(js[otherqueue][0]["message_id"], last_message_id)

        # get 2 rows and verify that we have one from each queue from the end
        r = self.get(messages_url + "?rows=2")
        js = r.json()
        self.assertEqual(len(js), 2)
        self.assertEqual(len(js[queue]), 1)
        self.assertEqual(js[queue][0]["message_id"], third_message_id)
        self.assertEqual(len(js[otherqueue]), 1)
        self.assertEqual(js[otherqueue][0]["message_id"], last_message_id)

    def test_messages_after(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        otherdata = {"message": {"Hello": "OtherWorld"}}
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.OK)
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)
        before_end_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.OK)
        last_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get only the top row and verify that it is correct, each time
        for i in range(0, 2):
            r = self.get(messages_url + "?messages_after=%s" % before_end_message_id)
            js = r.json()
            # Check we got one queue
            self.assertEqual(len(js), 1)
            # Check we got one message in the queue
            self.assertEqual(len(js[otherqueue]), 1)
            record = js[otherqueue][0]
            self.assertEqual(record["message_id"], last_message_id)
            self.assertEqual(record["payload"], otherdata["message"])

        # if we get by a larger number we should get nothing
        r = self.get(messages_url + "?messages_after=%s" % last_message_id)
        js = r.json()
        self.assertEqual(js, {})

        # if we get by zero we should get nothing, as we've previously acknowledged a valid top number
        r = self.get(messages_url + "?messages_after=%s" % '0')
        js = r.json()
        self.assertEqual(js, {})

        # if we get without a message number should get nothing, as we've previously acknowledged a valid top number
        r = self.get(messages_url)
        js = r.json()
        self.assertEqual(js, {})

        # Send additional messages
        player_sender = self.make_player()

        # Post additional messages
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.OK)
        before_end_message_id = r.json()["message_id"]
        r = self.post(othermessagequeue_url, data=otherdata, expected_status_code=http.client.OK)
        top_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get by zero should now return the two messages sent since last time
        r = self.get(messages_url + "?messages_after=%s" % (0))
        js = r.json()
        self.assertEqual(len(js), 1)
        self.assertEqual(len(js[otherqueue]), 2)
        # Messages are returned newest first
        self.assertEqual(js[otherqueue][0]["message_id"], top_message_id)
        self.assertEqual(js[otherqueue][1]["message_id"], before_end_message_id)

    def test_messages_multiplequeues(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        player_sender = self.make_player()
        num_queues = 5
        num_messages_per_queue = 3
        for i in range(num_queues):
            messagequeue_url = messagequeue_url_template.format(queue="testqueue-%s" % i)
            for j in range(num_messages_per_queue):
                data = {"message": {"Hello": "World", "queuenumber": i, "messagenumber": j}}
                r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the queues and delete them
        r = self.get(messages_url).json()

        self.assertEqual(len(r), num_queues)
        for queue, messages in r.items():
            self.assertEqual(len(messages), num_messages_per_queue)

    def test_messages_longpoll(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)
        message_url = r.json()["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the messages for the player using a 1 second long poll
        r = self.get(messages_url + "?timeout=1")
        self.assertIn("testqueue", r.json())
        self.assertEqual(len(r.json()["testqueue"]), 1)
        self.assertIn("payload", r.json()["testqueue"][0])
        self.assertIn("Hello", r.json()["testqueue"][0]["payload"])

    def test_message_expiry(self):
        player_receiver_endpoint, receiver_headers = self.make_player_message_endpoint_and_session()
        messagequeue_url_template, messages_url = self.get_messages_url(player_receiver_endpoint)

        # send a message from another player, with an expiry of one second
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {"message": {"Hello": "World"}, "expire": 1}
        self.post(messagequeue_url, data=data, expected_status_code=http.client.OK)

        # switch to the receiver player
        self.headers = receiver_headers

        with patch("driftbase.messages.utcnow") as mock_date:
            mock_date.return_value = datetime.datetime.utcnow() + datetime.timedelta(seconds=5)
            # all messages should have expired now
            r = self.get(messages_url + "?timeout=1")
            self.assertEqual(len(r.json()), 0)
