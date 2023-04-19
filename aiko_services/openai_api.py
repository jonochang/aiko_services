#!/usr/bin/env python3
#
# Usage
# ~~~~~
# export AIKO_LOG_LEVEL=DEBUG
# export AIKO_LOG_MQTT=false
# ./openai_api.py start
#
# ./openai_api.py test_command
#   Command: test_command(hello)
# ./openai_api.py test_request request_0
#   Response: [("request_0", [])]
#
# To Do
# ~~~~~
# - Compare "do_command()" and "do_request()" with AM / SSM
#   - Refactor into "service.py" ?
#
# - Consider GraphQL over MQTT !

from abc import abstractmethod
import click
import sqlite3
import openai
import os

from aiko_services import *
from aiko_services.transport import *
from aiko_services.utilities import *

ACTOR_TYPE = "openai_api_manager"
PROTOCOL = f"{ServiceProtocol.AIKO}/{ACTOR_TYPE}:0"

_LOGGER = aiko.logger(__name__)
_TOPIC_RESPONSE = f"{aiko.topic_out}/openai_api_response"
_VERSION = 0

# --------------------------------------------------------------------------- #

class OpenaiApiManager(Actor):
    Interface.implementations["OpenaiApiManager"] = "__main__.OpenaiApiManagerImpl"

    @abstractmethod
    def test_command(self, parameter):
        pass

    @abstractmethod
    def test_request(self, topic_path_response, request):
        pass

    @abstractmethod
    def prompt(self, topic_path_response, request):
        pass

class OpenaiApiManagerImpl(OpenaiApiManager):
    def __init__(self,
        implementations, name, protocol, tags, transport, database_pathname):

        implementations["Actor"].__init__(self,
            implementations, name, protocol, tags, transport)

        self.connection = sqlite3.connect(database_pathname)
        self.add_message_handler(self.topic_in_handler, self.topic_in)

        self.state = {
            "database_pathname": database_pathname,
            "lifecycle": "ready",
            "log_level": get_log_level_name(_LOGGER),
            "source_file": f"v{_VERSION}⇒{__file__}"
        }
        ec_producer = ECProducer(self, self.state)
        ec_producer.add_handler(self._ec_producer_change_handler)

# TODO: Move to ServiceImpl
    def _ec_producer_change_handler(self, command, item_name, item_value):
        if item_name == "log_level":
            _LOGGER.setLevel(str(item_value).upper())

    def test_command(self, parameter):
        print(f"Command: test_command({parameter})")

    def test_request(self, topic_path_response, request):
        aiko.message.publish(topic_path_response, "(item_count 1)")
        aiko.message.publish(topic_path_response, f"({request})")

    def prompt(self, topic_path_response, request):
        aiko.message.publish(topic_path_response, "(item_count 1)")
        aiko.message.publish(topic_path_response, f"({request})")

# TODO: Move to ActorImpl
    def topic_in_handler(self, _aiko, topic, payload_in):
        command, parameters = parse(payload_in)
        self._post_message(actor.Topic.IN, command, parameters)

# --------------------------------------------------------------------------- #

def do_command(actor_interface, command_handler, terminate=True):  # Refactor
    def actor_discovery_handler(command, service_details):
        if command == "add":
            event.remove_timer_handler(waiting_timer)
            topic_path = f"{service_details[0]}/in"
            actor = get_actor_mqtt(topic_path, actor_interface)
            command_handler(actor)
            if terminate:
                aiko.process.terminate()

    actor_discovery = ActorDiscovery(aiko.process)
    filter = ServiceFilter("*", "*", PROTOCOL, "*", "*", "*")
    actor_discovery.add_handler(actor_discovery_handler, filter)
    event.add_timer_handler(waiting_timer, 0.5)
    aiko.process.run()

item_count = 0
items_received = 0
response = []

def do_request(actor_interface, request_handler, response_handler):  # Refactor
    def topic_response_handler(_aiko, topic, payload_in):
        global item_count, items_received, response

        command, parameters = parse(payload_in)
        if command == "item_count" and len(parameters) == 1:
            item_count = int(parameters[0])
            items_received = 0
            response = []
        elif items_received < item_count:
            response.append((command, parameters))
            items_received += 1
            if items_received == item_count:
                response_handler(response)

    aiko.process.add_message_handler(topic_response_handler, _TOPIC_RESPONSE)
    do_command(actor_interface, request_handler, terminate=False)

def do_prompt(actor_interface, request_handler, response_handler):  # Refactor
    def topic_response_handler(_aiko, topic, payload_in):
        global item_count, items_received, response

        command, parameters = parse(payload_in)
        if command == "item_count" and len(parameters) == 1:
            item_count = int(parameters[0])
            items_received = 0
            response = []
        elif items_received < item_count:
            openai.api_key = os.environ.get('OPENAI_API_KEY')
            completion = openai.Completion.create(model="text-davinci-003", prompt=command, max_tokens=120, temperature=0, top_p=1, stream=False, echo=False, stop=None, frequency_penalty=0, presence_penalty=1, best_of=1)

            response.append(("openai prompt", command, "completion:", completion.choices[0].text))
            items_received += 1
            if items_received == item_count:
                response_handler(response)

    aiko.process.add_message_handler(topic_response_handler, _TOPIC_RESPONSE)
    do_command(actor_interface, request_handler, terminate=False)


def waiting_timer():
    event.remove_timer_handler(waiting_timer)
    print(f"Waiting for {ACTOR_TYPE}")

@click.group()
def main():
    pass

@main.command(help="Start OpenaiApiManager")
@click.argument("database_pathname", default="aiko_openai_api.db")
def start(database_pathname):
    tags = ["ec=true"]
    init_args = actor_args(ACTOR_TYPE, PROTOCOL, tags)
    init_args["database_pathname"] = database_pathname
    openai_api_manager = compose_instance(OpenaiApiManagerImpl, init_args)
    openai_api_manager.run()

@main.command(name="test_command")
def test_command():
    do_command(OpenaiApiManager, lambda openai_api_manager:
        openai_api_manager.test_command("hello")
    )

@main.command(name="test_request")
@click.argument("request")
def test_request(request):
    def response_handler(response):
        print(f"Response: {response}")
        import time; time.sleep(1)

    do_request(OpenaiApiManager,
        lambda openai_api_manager:
            openai_api_manager.test_request(_TOPIC_RESPONSE, request),
        response_handler
    )

@main.command(name="prompt")
@click.argument("request")
def prompt(request):
    #print(f"prompt:...", response)
    def response_handler(response):
        print(f"Completion: {response}")
        import time; time.sleep(1)

    do_prompt(OpenaiApiManager,
        lambda openai_api_manager:
            openai_api_manager.test_request(_TOPIC_RESPONSE, request),
        response_handler
    )

if __name__ == "__main__":
    main()

# --------------------------------------------------------------------------- #
