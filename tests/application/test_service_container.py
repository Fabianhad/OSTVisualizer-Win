import gc
import unittest
import weakref
from ost_visualizer.application.service_container import ServiceContainer


class Shutdownable:
    pass


class ShutdownableChild(Shutdownable):
    pass


class Unrelated:
    pass


class CountingFactory:
    def __init__(self, product=None):
        self.calls = 0
        self._product = product

    def __call__(self):
        self.calls += 1
        if self._product is not None:
            return self._product
        return Unrelated()


class RegisterInstanceTests(unittest.TestCase):
    def test_get_returns_the_registered_instance_itself(self):
        container = ServiceContainer()
        service = Unrelated()
        container.register_instance("service", service)
        self.assertIs(container.get("service"), service)
        self.assertIs(container.get("service"), service)

    def test_falsy_instances_are_returned_not_treated_as_missing(self):
        container = ServiceContainer()
        for name, value in (
            ("zero", 0),
            ("empty", ""),
            ("none", None),
            ("flag", False),
        ):
            with self.subTest(name=name):
                container.register_instance(name, value)
                self.assertIs(container.get(name), value)

    def test_registering_the_same_name_again_replaces_the_instance(self):
        container = ServiceContainer()
        first, second = Unrelated(), Unrelated()
        container.register_instance("service", first)
        container.register_instance("service", second)
        self.assertIs(container.get("service"), second)

    def test_names_are_independent(self):
        container = ServiceContainer()
        first, second = Unrelated(), Unrelated()
        container.register_instance("first", first)
        container.register_instance("second", second)
        self.assertIs(container.get("first"), first)
        self.assertIs(container.get("second"), second)

    def test_containers_do_not_share_registrations(self):
        first, second = ServiceContainer(), ServiceContainer()
        first.register_instance("service", Unrelated())
        with self.assertRaises(KeyError):
            second.get("service")


class RegisterSingletonTests(unittest.TestCase):
    def test_registering_a_singleton_does_not_create_it(self):
        container = ServiceContainer()
        factory = CountingFactory()
        container.register_singleton("service", factory)
        self.assertEqual(factory.calls, 0)

    def test_the_first_get_creates_it_and_later_gets_return_the_same_object(self):
        container = ServiceContainer()
        factory = CountingFactory()
        container.register_singleton("service", factory)
        first = container.get("service")
        second = container.get("service")
        self.assertEqual(factory.calls, 1)
        self.assertIs(first, second)
        self.assertIsInstance(first, Unrelated)

    def test_each_singleton_is_created_independently_and_only_when_requested(self):
        container = ServiceContainer()
        first_factory, second_factory = CountingFactory(), CountingFactory()
        container.register_singleton("first", first_factory)
        container.register_singleton("second", second_factory)
        container.get("first")
        self.assertEqual((first_factory.calls, second_factory.calls), (1, 0))
        container.get("second")
        container.get("second")
        self.assertEqual((first_factory.calls, second_factory.calls), (1, 1))
        self.assertIsNot(container.get("first"), container.get("second"))

    def test_a_factory_that_builds_a_service_may_get_other_services(self):
        container = ServiceContainer()
        dependency = Unrelated()
        container.register_instance("dependency", dependency)
        container.register_singleton("consumer", lambda: [container.get("dependency")])
        self.assertEqual(container.get("consumer"), [dependency])
        self.assertIs(container.get("consumer"), container.get("consumer"))

    def test_a_factory_that_returns_none_is_called_again_on_every_get(self):
        container = ServiceContainer()
        calls = []

        def returns_none():
            calls.append(1)
            return None

        container.register_singleton("service", returns_none)
        self.assertIsNone(container.get("service"))
        self.assertIsNone(container.get("service"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(container.get_by_interface(object), [])

    def test_falsy_products_are_cached_like_any_other_product(self):
        for product in (0, "", [], False):
            with self.subTest(product=product):
                container = ServiceContainer()
                factory = CountingFactory(product)
                container.register_singleton("service", factory)
                self.assertEqual(container.get("service"), product)
                self.assertIs(container.get("service"), container.get("service"))
                self.assertEqual(factory.calls, 1)

    def test_a_factory_error_propagates_and_the_next_get_retries(self):
        container = ServiceContainer()
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("boom")
            return Unrelated()

        container.register_singleton("service", flaky)
        with self.assertRaises(RuntimeError):
            container.get("service")
        created = container.get("service")
        self.assertEqual(len(attempts), 2)
        self.assertIs(container.get("service"), created)

    def test_registering_a_singleton_again_replaces_the_factory_and_cached_object(
        self,
    ):
        container = ServiceContainer()
        first_factory, second_factory = CountingFactory(), CountingFactory()
        container.register_singleton("service", first_factory)
        first = container.get("service")
        container.register_singleton("service", second_factory)
        self.assertEqual(second_factory.calls, 0)
        second = container.get("service")
        self.assertIsNot(second, first)
        self.assertEqual((first_factory.calls, second_factory.calls), (1, 1))
        self.assertIs(container.get("service"), second)


class GetTests(unittest.TestCase):
    def test_a_missing_name_raises_a_key_error_naming_the_service(self):
        container = ServiceContainer()
        with self.assertRaises(KeyError) as raised:
            container.get("missing")
        self.assertEqual(raised.exception.args, ("Service 'missing' not found",))

    def test_names_are_exact_and_case_sensitive(self):
        container = ServiceContainer()
        container.register_instance("Service", Unrelated())
        for name in ("service", "Service ", ""):
            with self.subTest(name=name):
                with self.assertRaises(KeyError):
                    container.get(name)

    def test_a_registered_instance_wins_over_a_singleton_of_the_same_name(self):
        container = ServiceContainer()
        factory = CountingFactory()
        instance = Unrelated()
        container.register_singleton("service", factory)
        container.register_instance("service", instance)
        self.assertIs(container.get("service"), instance)
        self.assertEqual(factory.calls, 0)

    def test_an_instance_registered_first_still_wins_over_a_later_singleton(self):
        container = ServiceContainer()
        factory = CountingFactory()
        instance = Unrelated()
        container.register_instance("service", instance)
        container.register_singleton("service", factory)
        self.assertIs(container.get("service"), instance)
        self.assertEqual(factory.calls, 0)


class GetByInterfaceTests(unittest.TestCase):
    def test_it_returns_instances_that_are_instances_of_the_interface(self):
        container = ServiceContainer()
        parent, child, other = Shutdownable(), ShutdownableChild(), Unrelated()
        container.register_instance("parent", parent)
        container.register_instance("child", child)
        container.register_instance("other", other)
        found = container.get_by_interface(Shutdownable)
        self.assertEqual(len(found), 2)
        self.assertIn(parent, found)
        self.assertIn(child, found)

    def test_a_subclass_interface_excludes_its_parent(self):
        container = ServiceContainer()
        parent, child = Shutdownable(), ShutdownableChild()
        container.register_instance("parent", parent)
        container.register_instance("child", child)
        self.assertEqual(container.get_by_interface(ShutdownableChild), [child])

    def test_created_singletons_are_included(self):
        container = ServiceContainer()
        product = ShutdownableChild()
        container.register_singleton("service", CountingFactory(product))
        container.get("service")
        self.assertEqual(container.get_by_interface(Shutdownable), [product])

    def test_uncreated_singletons_are_neither_created_nor_included(self):
        container = ServiceContainer()
        factory = CountingFactory(ShutdownableChild())
        container.register_singleton("service", factory)
        self.assertEqual(container.get_by_interface(Shutdownable), [])
        self.assertEqual(container.get_by_interface(object), [])
        self.assertEqual(factory.calls, 0)

    def test_instances_come_before_created_singletons(self):
        container = ServiceContainer()
        instance, product = Shutdownable(), ShutdownableChild()
        container.register_singleton("lazy", CountingFactory(product))
        container.register_instance("eager", instance)
        container.get("lazy")
        self.assertEqual(container.get_by_interface(Shutdownable), [instance, product])

    def test_nothing_registered_or_nothing_matching_gives_an_empty_list(self):
        container = ServiceContainer()
        self.assertEqual(container.get_by_interface(Shutdownable), [])
        container.register_instance("other", Unrelated())
        self.assertEqual(container.get_by_interface(Shutdownable), [])

    def test_the_result_is_a_new_list_each_call(self):
        container = ServiceContainer()
        container.register_instance("service", Shutdownable())
        first = container.get_by_interface(Shutdownable)
        first.clear()
        self.assertEqual(len(container.get_by_interface(Shutdownable)), 1)


class ClearTests(unittest.TestCase):
    def test_clear_removes_instances_and_created_and_uncreated_singletons(self):
        container = ServiceContainer()
        container.register_instance("instance", Shutdownable())
        container.register_singleton("created", CountingFactory())
        container.register_singleton("uncreated", CountingFactory())
        container.get("created")
        container.clear()
        for name in ("instance", "created", "uncreated"):
            with self.subTest(name=name):
                with self.assertRaises(KeyError):
                    container.get(name)
        self.assertEqual(container.get_by_interface(object), [])

    def test_clear_releases_the_factories(self):
        container = ServiceContainer()
        factory = CountingFactory()
        reference = weakref.ref(factory)
        container.register_singleton("service", factory)
        del factory
        container.clear()
        gc.collect()
        self.assertIsNone(reference())

    def test_clear_never_calls_a_pending_factory(self):
        container = ServiceContainer()
        factory = CountingFactory()
        container.register_singleton("service", factory)
        container.clear()
        self.assertEqual(factory.calls, 0)

    def test_a_cleared_container_accepts_new_registrations(self):
        container = ServiceContainer()
        old_factory, new_factory = CountingFactory(), CountingFactory()
        container.register_singleton("service", old_factory)
        old = container.get("service")
        container.clear()
        container.register_singleton("service", new_factory)
        new = container.get("service")
        self.assertIsNot(new, old)
        self.assertEqual((old_factory.calls, new_factory.calls), (1, 1))

    def test_clearing_an_empty_container_is_harmless(self):
        container = ServiceContainer()
        container.clear()
        container.clear()
        self.assertEqual(container.get_by_interface(object), [])


if __name__ == "__main__":
    unittest.main()
