# -*- coding: utf-8 -*-
from six.moves import http_client
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
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messages_url = r.json()["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        messagequeue_url = messagequeue_url_template.format(queue="testqueue")
        data = {
            "message" : {"Hello": "World"}
        }
        r = self.post(messagequeue_url, data=data)
        message_url = r.json()["url"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the messages for the player
        r = self.get(messages_url)
        js = r.json()
        self.assertIn("testqueue", r.json())
        self.assertEquals(len(r.json()["testqueue"]), 1)
        self.assertIn("payload", r.json()["testqueue"][0])
        self.assertIn("Hello", r.json()["testqueue"][0]["payload"])

        # get all the messages for the player again and make sure we're receiving the same thing
        r = self.get(messages_url)
        self.assertEquals(r.json(), js)

        # get the messages and this time clear them as well
        r = self.get(messages_url + "?delete=true")
        js = r.json()
        self.assertIn("testqueue", r.json())
        self.assertEquals(len(r.json()["testqueue"]), 1)
        self.assertIn("payload", r.json()["testqueue"][0])
        self.assertIn("Hello", r.json()["testqueue"][0]["payload"])

    def test_messages_rows(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messages_url = r.json()["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=data)
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=data)

        top_message_number = r.json()["message_number"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get all messages
        r = self.get(messages_url)
        js = r.json()
        self.assertEquals(len(js), 2)
        self.assertEquals(len(js[queue]), 2)
        self.assertEquals(len(js[otherqueue]), 2)

        # get 1 row and verify that it is the latest one
        r = self.get(messages_url + "?rows=1")
        js = r.json()
        self.assertEquals(len(js), 1)
        self.assertNotIn(queue, js)
        self.assertEquals(len(js[otherqueue]), 1)
        self.assertEquals(js[otherqueue][0]["message_number"], top_message_number)

        # get 2 rows and verify that we have one from each queue
        r = self.get(messages_url + "?rows=2")
        js = r.json()
        self.assertEquals(len(js), 2)
        self.assertEquals(len(js[queue]), 1)
        self.assertEquals(len(js[otherqueue]), 1)

    def test_messages_after(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messages_url = r.json()["messages_url"]

        # send a message from another player
        player_sender = self.make_player()
        queue = "testqueue"
        messagequeue_url = messagequeue_url_template.format(queue=queue)
        data = {"message": {"Hello": "World"}}
        otherqueue = "othertestqueue"
        othermessagequeue_url = messagequeue_url_template.format(queue=otherqueue)
        data = {"message": {"Hello": "World"}}
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=data)
        r = self.post(messagequeue_url, data=data)
        r = self.post(othermessagequeue_url, data=data)

        top_message_number = int(r.json()["message_number"])
        top_message_id = r.json()["message_id"]

        # switch to the receiver player
        self.headers = receiver_headers

        # get only the top row and verify that it is correct
        r = self.get(messages_url + "?messages_after=%s" %
                     (top_message_number - 1))
        js = r.json()
        self.assertEquals(len(js), 1)
        self.assertEquals(len(js[otherqueue]), 1)
        self.assertEquals(js[otherqueue][0]["message_number"], top_message_number)
        self.assertEquals(js[otherqueue][0]["message_id"], top_message_id)

        # if we get by a larger number we should get nothing
        r = self.get(messages_url + "?messages_after=%s" % (top_message_number))
        js = r.json()
        self.assertEquals(js, {})

    def test_messages_multiplequeues(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers
        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
        messages_url = r.json()["messages_url"]

        player_sender = self.make_player()
        num_queues = 5
        num_messages_per_queue = 3
        for i in xrange(num_queues):
            messagequeue_url = messagequeue_url_template.format(queue="testqueue-%s" % i)
            for j in xrange(num_messages_per_queue):
                data = {"message": {"Hello": "World", "queuenumber": i, "messagenumber": j}}
                r = self.post(messagequeue_url, data=data)
                self.assertIn("payload", r.json())
                self.assertEquals(r.json()["payload"]["queuenumber"], i)
                self.assertEquals(r.json()["payload"]["messagenumber"], j)

        # switch to the receiver player
        self.headers = receiver_headers

        # get all the queues and delete them
        r = self.get(messages_url)

        self.assertEquals(len(r.json()), num_queues)
        for queue, messages in r.json().iteritems():
            self.assertEquals(len(messages), num_messages_per_queue)

    def test_messages_longpoll(self):
        player_receiver = self.make_player()
        receiver_headers = self.headers

        player_receiver_endpoint = self.endpoints["my_player"]
        r = self.get(player_receiver_endpoint)
        messagequeue_url_template = r.json()["messagequeue_url"]
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
        self.assertEquals(len(r.json()["testqueue"]), 1)
        self.assertIn("payload", r.json()["testqueue"][0])
        self.assertIn("Hello", r.json()["testqueue"][0]["payload"])
