from enum import Enum

from homeassistant_api import Client
from decouple import config
class HAServiceEnum(Enum):
    turn_on = "turn_on"
    turn_off = "turn_off"
    toggle = "toggle"


class JGHAClient:
    def __init__(self):
        self.client = Client(api_url=config("HA_API_URL"), token=config("HA_TOKEN"), use_async=False)


    def get_entity_state(self, entity_id):
        """Get the state of an entity."""
        return self.client.get_entity(entity_id=entity_id)

    def get_all_entities(self):
        """Get all entities."""
        return self.client.get_entities()

    def trigger_service(self, domain, service, **kwargs):
        """Trigger a service."""
        return self.client.trigger_service(domain=domain, service=service, **kwargs)

    def trigger_light_service(self, entity_id: str, service: HAServiceEnum = HAServiceEnum.toggle):
        """Trigger a light service."""
        return self.trigger_service(domain="light", service=service.value, entity_id=entity_id)



if __name__ == "__main__":
    client = JGHAClient()
    entity_id = "light.schreibtisch_candle_leuchte"
    #state = client.get_entity_state(entity_id)
    #print(f"The state of {entity_id} is: {state}")
    # print(f"All entities:\n{client.get_all_entities()}")
    client.trigger_light_service(entity_id)
