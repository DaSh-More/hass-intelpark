from custom_components.intelpark.entity import object_device_info


def test_object_device_info():
    info = object_device_info("entry123", "Мой дом")
    assert info["identifiers"] == {("intelpark", "entry123:Мой дом")}
    assert info["name"] == "Мой дом"
