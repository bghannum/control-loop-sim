from engine.models.base import MODEL_REGISTRY, PlantModel, register_model


def test_register_model_adds_to_registry():
    MODEL_REGISTRY.clear()

    @register_model("dummy")
    class DummyModel(PlantModel):
        def step(self, state, control_input, dt):
            return state

        def initial_state(self):
            return {"temperature": 0.0}

    assert MODEL_REGISTRY["dummy"] is DummyModel
