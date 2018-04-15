from piston3.handler import (
    AnonymousBaseHandler,
    BaseHandler,
    HandlerMetaClass,
)
from maasserver.models.node import Device


class TestHandler(BaseHandler):
    """Manage the collection of all the devices in the MAAS."""
    # api_doc_section_name = "Devices"
    update = delete = None
    base_model = Device

    def create(self, request):
        return  "nihao"

    def read(self, request):
        return  "nihao a,  i am yin"

    @classmethod
    def resource_uri(cls, *args, **kwargs):
        return ('test_heandler', [])