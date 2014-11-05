# Copyright 2012-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for node actions."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

import random
from urlparse import urlparse

from django.core.urlresolvers import reverse
from maasserver import locks
from maasserver.clusterrpc.utils import get_error_message_for_exception
from maasserver.enum import (
    NODE_BOOT,
    NODE_PERMISSION,
    NODE_STATUS,
    NODE_STATUS_CHOICES,
    NODE_STATUS_CHOICES_DICT,
    POWER_STATE,
    )
from maasserver.exceptions import (
    NodeActionError,
    Redirect,
    )
from maasserver.models import StaticIPAddress
from maasserver.node_action import (
    AbortCommissioning,
    AbortOperation,
    AcquireNode,
    Commission,
    compile_node_actions,
    Delete,
    MarkBroken,
    MarkFixed,
    NodeAction,
    ReleaseNode,
    RPC_EXCEPTIONS,
    StartNode,
    StopNode,
    UseCurtin,
    UseDI,
    )
from maasserver.node_status import FAILED_STATUSES
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_object
from maasserver.testing.testcase import MAASServerTestCase
from maastesting.matchers import MockCalledOnceWith
from mock import ANY
from provisioningserver.rpc.exceptions import MultipleFailures
from provisioningserver.utils.shell import ExternalProcessError
from testtools.matchers import Equals
from twisted.python.failure import Failure


ALL_STATUSES = NODE_STATUS_CHOICES_DICT.keys()


class FakeNodeAction(NodeAction):
    name = "fake"
    display = "Action label"
    display_bulk = "Action label bulk"
    actionable_statuses = ALL_STATUSES
    permission = NODE_PERMISSION.VIEW

    # For testing: an inhibition for inhibit() to return.
    fake_inhibition = None

    def inhibit(self):
        return self.fake_inhibition

    def execute(self):
        pass


class TestNodeAction(MAASServerTestCase):

    def test_compile_node_actions_returns_available_actions(self):

        class MyAction(FakeNodeAction):
            name = factory.make_string()

        actions = compile_node_actions(
            factory.make_Node(), factory.make_admin(), classes=[MyAction])
        self.assertEqual([MyAction.name], actions.keys())

    def test_compile_node_actions_checks_node_status(self):

        class MyAction(FakeNodeAction):
            actionable_statuses = (NODE_STATUS.READY, )

        node = factory.make_Node(status=NODE_STATUS.NEW)
        actions = compile_node_actions(
            node, factory.make_admin(), classes=[MyAction])
        self.assertEqual({}, actions)

    def test_compile_node_actions_checks_permission(self):

        class MyAction(FakeNodeAction):
            permission = NODE_PERMISSION.EDIT

        node = factory.make_Node(status=NODE_STATUS.COMMISSIONING)
        actions = compile_node_actions(
            node, factory.make_User(), classes=[MyAction])
        self.assertEqual({}, actions)

    def test_compile_node_actions_includes_inhibited_actions(self):

        class MyAction(FakeNodeAction):
            fake_inhibition = factory.make_string()

        actions = compile_node_actions(
            factory.make_Node(), factory.make_admin(), classes=[MyAction])
        self.assertEqual([MyAction.name], actions.keys())

    def test_compile_node_actions_maps_names(self):

        class Action1(FakeNodeAction):
            name = factory.make_string()

        class Action2(FakeNodeAction):
            name = factory.make_string()

        actions = compile_node_actions(
            factory.make_Node(), factory.make_admin(),
            classes=[Action1, Action2])
        for name, action in actions.items():
            self.assertEqual(name, action.name)

    def test_compile_node_actions_maintains_order(self):
        names = [factory.make_string() for counter in range(4)]
        classes = [
            type(b"Action%d" % counter, (FakeNodeAction,), {'name': name})
            for counter, name in enumerate(names)]
        actions = compile_node_actions(
            factory.make_Node(), factory.make_admin(), classes=classes)
        self.assertSequenceEqual(names, actions.keys())
        self.assertSequenceEqual(
            names, [action.name for action in actions.values()])

    def test_is_permitted_allows_if_user_has_permission(self):

        class MyAction(FakeNodeAction):
            permission = NODE_PERMISSION.EDIT

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User())
        self.assertTrue(MyAction(node, node.owner).is_permitted())

    def test_is_permitted_disallows_if_user_lacks_permission(self):

        class MyAction(FakeNodeAction):
            permission = NODE_PERMISSION.EDIT

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User())
        self.assertFalse(MyAction(node, factory.make_User()).is_permitted())

    def test_inhibition_wraps_inhibit(self):
        inhibition = factory.make_string()
        action = FakeNodeAction(factory.make_Node(), factory.make_User())
        action.fake_inhibition = inhibition
        self.assertEqual(inhibition, action.inhibition)

    def test_inhibition_caches_inhibition(self):
        # The inhibition property will call inhibit() only once.  We can
        # prove this by changing the string inhibit() returns; it won't
        # affect the value of the property.
        inhibition = factory.make_string()
        action = FakeNodeAction(factory.make_Node(), factory.make_User())
        action.fake_inhibition = inhibition
        self.assertEqual(inhibition, action.inhibition)
        action.fake_inhibition = factory.make_string()
        self.assertEqual(inhibition, action.inhibition)

    def test_inhibition_caches_None(self):
        # An inhibition of None is also faithfully cached.  In other
        # words, it doesn't get mistaken for an uninitialized cache or
        # anything.
        action = FakeNodeAction(factory.make_Node(), factory.make_User())
        action.fake_inhibition = None
        self.assertIsNone(action.inhibition)
        action.fake_inhibition = factory.make_string()
        self.assertIsNone(action.inhibition)


class TestDeleteNodeAction(MAASServerTestCase):

    def test_Delete_redirects_to_node_delete_view(self):
        node = factory.make_Node()
        action = Delete(node, factory.make_admin())
        try:
            action.execute()
        except Redirect as e:
            pass
        self.assertEqual(
            reverse('node-delete', args=[node.system_id]),
            urlparse(unicode(e)).path)


class TestCommissionNodeAction(MAASServerTestCase):

    scenarios = (
        ("NEW", {"status": NODE_STATUS.NEW}),
        ("FAILED_COMMISSIONING", {
            "status": NODE_STATUS.FAILED_COMMISSIONING}),
        ("READY", {"status": NODE_STATUS.READY}),
    )

    def test_Commission_starts_commissioning(self):
        node = factory.make_Node(
            mac=True, status=self.status,
            power_type='ether_wake')
        self.patch_autospec(node, 'start_transition_monitor')
        node_start = self.patch(node, 'start')
        admin = factory.make_admin()
        action = Commission(node, admin)
        action.execute()
        self.assertEqual(NODE_STATUS.COMMISSIONING, node.status)
        self.assertThat(
            node_start, MockCalledOnceWith(admin, user_data=ANY))


class TestAbortCommissioningNodeAction(MAASServerTestCase):

    def test_AbortCommissioning_aborts_commissioning(self):
        node = factory.make_Node(
            mac=True, status=NODE_STATUS.COMMISSIONING,
            power_type='virsh')
        self.patch_autospec(node, 'stop_transition_monitor')
        node_stop = self.patch_autospec(node, 'stop')
        admin = factory.make_admin()

        AbortCommissioning(node, admin).execute()
        self.assertEqual(NODE_STATUS.NEW, node.status)
        self.assertThat(node_stop, MockCalledOnceWith(admin))


class TestAbortOperationNodeAction(MAASServerTestCase):

    def test_AbortOperation_aborts_disk_erasing(self):
        owner = factory.make_User()
        node = factory.make_Node(
            status=NODE_STATUS.DISK_ERASING, owner=owner)
        node_stop = self.patch_autospec(node, 'stop')

        AbortOperation(node, owner).execute()

        self.assertEqual(NODE_STATUS.FAILED_DISK_ERASING, node.status)
        self.assertThat(node_stop, MockCalledOnceWith(owner))


class TestAcquireNodeNodeAction(MAASServerTestCase):

    def test_AcquireNode_acquires_node(self):
        node = factory.make_Node(
            mac=True, status=NODE_STATUS.READY,
            power_type='ether_wake')
        user = factory.make_User()
        AcquireNode(node, user).execute()
        self.assertEqual(NODE_STATUS.ALLOCATED, node.status)
        self.assertEqual(user, node.owner)

    def test_AcquireNode_uses_node_acquire_lock(self):
        node = factory.make_Node(
            mac=True, status=NODE_STATUS.READY,
            power_type='ether_wake')
        user = factory.make_User()
        node_acquire = self.patch(locks, 'node_acquire')
        AcquireNode(node, user).execute()
        self.assertThat(node_acquire.__enter__, MockCalledOnceWith())
        self.assertThat(
            node_acquire.__exit__, MockCalledOnceWith(None, None, None))


class TestStartNodeNodeAction(MAASServerTestCase):

    def test_StartNode_inhibit_allows_user_with_SSH_key(self):
        user_with_key = factory.make_User()
        factory.make_SSHKey(user_with_key)
        self.assertIsNone(
            StartNode(factory.make_Node(), user_with_key).inhibit())

    def test_StartNode_inhibit_disallows_user_without_SSH_key(self):
        user_without_key = factory.make_User()
        action = StartNode(factory.make_Node(), user_without_key)
        inhibition = action.inhibit()
        self.assertIsNotNone(inhibition)
        self.assertIn("SSH key", inhibition)

    def test_StartNode_starts_node(self):
        user = factory.make_User()
        node = factory.make_Node(
            mac=True, status=NODE_STATUS.ALLOCATED,
            power_type='ether_wake', owner=user)
        node_start = self.patch(node, 'start')
        StartNode(node, user).execute()
        self.assertThat(
            node_start, MockCalledOnceWith(user))

    def test_StartNode_returns_error_when_no_more_static_IPs(self):
        user = factory.make_User()
        node = factory.make_node_with_mac_attached_to_nodegroupinterface(
            status=NODE_STATUS.ALLOCATED, power_type='ether_wake', owner=user,
            power_state=POWER_STATE.OFF)
        ngi = node.get_primary_mac().cluster_interface

        # Narrow the available IP range and pre-claim the only address.
        ngi.static_ip_range_high = ngi.static_ip_range_low
        ngi.save()
        StaticIPAddress.objects.allocate_new(
            ngi.static_ip_range_high, ngi.static_ip_range_low)

        e = self.assertRaises(NodeActionError, StartNode(node, user).execute)
        self.expectThat(
            e.message, Equals(
                "%s: Failed to start, static IP addresses are exhausted." %
                node.hostname))
        self.assertEqual(NODE_STATUS.ALLOCATED, node.status)

    def test_StartNode_requires_edit_permission(self):
        user = factory.make_User()
        node = factory.make_Node()
        self.assertFalse(
            user.has_perm(NODE_PERMISSION.EDIT, node))
        self.assertFalse(StartNode(node, user).is_permitted())

    def test_StartNode_allocates_node_if_node_not_already_allocated(self):
        user = factory.make_User()
        node = factory.make_Node(status=NODE_STATUS.READY)
        self.patch(node, 'start')
        action = StartNode(node, user)
        action.execute()

        self.assertEqual(user, node.owner)
        self.assertEqual(NODE_STATUS.ALLOCATED, node.status)

    def test_StartNode_label_shows_allocate_if_unallocated(self):
        user = factory.make_User()
        node = factory.make_Node(status=NODE_STATUS.READY)
        self.patch(node, 'start')
        action = StartNode(node, user)
        self.assertEqual("Acquire and start node", action.display)

    def test_StartNode_label_hides_allocate_if_allocated(self):
        user = factory.make_User()
        node = factory.make_Node(status=NODE_STATUS.READY)
        self.patch(node, 'start')
        node.acquire(user)
        action = StartNode(node, user)
        self.assertEqual("Start node", action.display)

    def test_StartNode_label_hides_acquire_for_non_owner_admin(self):
        user = factory.make_User()
        admin = factory.make_admin()
        node = factory.make_Node(status=NODE_STATUS.READY)
        node.acquire(user)
        action = StartNode(node, admin)
        self.assertEqual("Start node", action.display)

    def test_StartNode_does_not_reallocate_when_run_by_non_owner(self):
        user = factory.make_User()
        admin = factory.make_admin()
        node = factory.make_Node(status=NODE_STATUS.READY)
        self.patch(node, 'start')
        node.acquire(user)
        action = StartNode(node, admin)

        # This action.execute() will not fail because the non-owner is
        # an admin, so they can start the node. Even if they weren't an
        # admin, the node still wouldn't start; Node.start() would
        # ignore it.
        action.execute()
        self.assertEqual(user, node.owner)
        self.assertEqual(NODE_STATUS.ALLOCATED, node.status)


class TestStopNodeNodeAction(MAASServerTestCase):

    def test__stops_deployed_node(self):
        user = factory.make_User()
        params = dict(
            power_address=factory.make_string(),
            power_user=factory.make_string(),
            power_pass=factory.make_string())
        node = factory.make_Node(
            mac=True, status=NODE_STATUS.DEPLOYED,
            power_type='ipmi',
            owner=user, power_parameters=params)
        node_stop = self.patch_autospec(node, 'stop')

        StopNode(node, user).execute()

        self.assertThat(node_stop, MockCalledOnceWith(user))

    def test__stops_Ready_node(self):
        admin = factory.make_admin()
        params = dict(
            power_address=factory.make_string(),
            power_user=factory.make_string(),
            power_pass=factory.make_string())
        node = factory.make_Node(
            mac=True, status=NODE_STATUS.READY,
            power_type='ipmi', power_parameters=params)
        node_stop = self.patch_autospec(node, 'stop')

        StopNode(node, admin).execute()

        self.assertThat(node_stop, MockCalledOnceWith(admin))

    def test__actionnable_for_failed_states(self):
        status = random.choice(FAILED_STATUSES)
        node = factory.make_Node(status=status, power_type='ipmi')
        actions = compile_node_actions(
            node, factory.make_admin(), classes=[StopNode])
        self.assertItemsEqual([StopNode.name], actions)


ACTIONABLE_STATUSES = [
    NODE_STATUS.DEPLOYING,
    NODE_STATUS.FAILED_DEPLOYMENT,
    NODE_STATUS.FAILED_DISK_ERASING,
]


class TestReleaseNodeNodeAction(MAASServerTestCase):

    scenarios = [
        (NODE_STATUS_CHOICES_DICT[status], dict(actionable_status=status))
        for status in ACTIONABLE_STATUSES
    ]

    def test_ReleaseNode_stops_and_releases_node(self):
        user = factory.make_User()
        params = dict(
            power_address=factory.make_string(),
            power_user=factory.make_string(),
            power_pass=factory.make_string())
        node = factory.make_Node(
            mac=True, status=self.actionable_status,
            power_type='ipmi',
            owner=user, power_parameters=params)
        node_stop = self.patch_autospec(node, 'stop')

        ReleaseNode(node, user).execute()

        self.expectThat(node.status, Equals(NODE_STATUS.RELEASING))
        self.assertThat(
            node_stop, MockCalledOnceWith(user))


class TestUseCurtinNodeAction(MAASServerTestCase):

    def test_sets_boot_type(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user, boot_type=NODE_BOOT.DEBIAN)
        action = UseCurtin(node, user)
        self.assertTrue(action.is_permitted())
        action.execute()
        self.assertEqual(NODE_BOOT.FASTPATH, node.boot_type)

    def test_requires_edit_permission(self):
        user = factory.make_User()
        node = factory.make_Node(boot_type=NODE_BOOT.DEBIAN)
        self.assertFalse(UseCurtin(node, user).is_permitted())

    def test_not_permitted_if_already_uses_curtin(self):
        node = factory.make_Node(boot_type=NODE_BOOT.FASTPATH)
        user = factory.make_admin()
        self.assertFalse(UseCurtin(node, user).is_permitted())


class TestUseDINodeAction(MAASServerTestCase):

    def test_sets_boot_type(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user, boot_type=NODE_BOOT.FASTPATH)
        action = UseDI(node, user)
        self.assertTrue(action.is_permitted())
        action.execute()
        self.assertEqual(NODE_BOOT.DEBIAN, node.boot_type)

    def test_requires_edit_permission(self):
        user = factory.make_User()
        node = factory.make_Node(boot_type=NODE_BOOT.FASTPATH)
        self.assertFalse(UseDI(node, user).is_permitted())

    def test_not_permitted_if_already_uses_di(self):
        node = factory.make_Node(boot_type=NODE_BOOT.DEBIAN)
        user = factory.make_admin()
        self.assertFalse(UseDI(node, user).is_permitted())


class TestMarkBrokenAction(MAASServerTestCase):

    def test_changes_status(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user, status=NODE_STATUS.COMMISSIONING)
        action = MarkBroken(node, user)
        self.assertTrue(action.is_permitted())
        action.execute()
        self.assertEqual(NODE_STATUS.BROKEN, reload_object(node).status)

    def test_updates_error_description(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user, status=NODE_STATUS.COMMISSIONING)
        action = MarkBroken(node, user)
        self.assertTrue(action.is_permitted())
        action.execute()
        self.assertEqual(
            "Manually marked as broken by user '%s'" % user.username,
            reload_object(node).error_description
        )

    def test_requires_edit_permission(self):
        user = factory.make_User()
        node = factory.make_Node()
        self.assertFalse(MarkBroken(node, user).is_permitted())


class TestMarkFixedAction(MAASServerTestCase):

    def test_changes_status(self):
        node = factory.make_Node(status=NODE_STATUS.BROKEN)
        user = factory.make_admin()
        action = MarkFixed(node, user)
        self.assertTrue(action.is_permitted())
        action.execute()
        self.assertEqual(NODE_STATUS.READY, reload_object(node).status)

    def test_requires_admin_permission(self):
        user = factory.make_User()
        node = factory.make_Node()
        self.assertFalse(MarkFixed(node, user).is_permitted())

    def test_not_enabled_if_not_broken(self):
        status = factory.pick_choice(
            NODE_STATUS_CHOICES, but_not=[NODE_STATUS.BROKEN])
        node = factory.make_Node(status=status)
        actions = compile_node_actions(
            node, factory.make_admin(), classes=[MarkFixed])
        self.assertItemsEqual([], actions)


class TestActionsErrorHandling(MAASServerTestCase):
    """Tests for error handling in actions.

    This covers RPC exceptions and `ExternalProcessError`s.
    """
    exceptions = RPC_EXCEPTIONS + (ExternalProcessError,)
    scenarios = [
        (exception_class.__name__, {"exception_class": exception_class})
        for exception_class in exceptions
        ]

    def make_exception(self):
        if self.exception_class is MultipleFailures:
            exception = self.exception_class(
                Failure(Exception(factory.make_name("exception"))))
        elif self.exception_class is ExternalProcessError:
            exception = self.exception_class(
                1, ["cmd"], factory.make_name("exception"))
        else:
            exception = self.exception_class(factory.make_name("exception"))
        return exception

    def patch_rpc_methods(self, node):
        exception = self.make_exception()
        self.patch(node, 'start').side_effect = exception
        self.patch(node, 'stop').side_effect = exception
        self.patch_autospec(node, 'start_transition_monitor')
        self.patch_autospec(node, 'stop_transition_monitor')

    def make_action(self, action_class, node_status):
        node = factory.make_Node(
            mac=True, status=node_status, power_type='ether_wake')
        admin = factory.make_admin()
        return action_class(node, admin)

    def test_Commission_handles_rpc_errors(self):
        action = self.make_action(Commission, NODE_STATUS.READY)
        self.patch_rpc_methods(action.node)
        exception = self.assertRaises(NodeActionError, action.execute)
        self.assertEqual(
            get_error_message_for_exception(
                action.node.start.side_effect),
            unicode(exception))

    def test_AbortCommissioning_handles_rpc_errors(self):
        action = self.make_action(
            AbortCommissioning, NODE_STATUS.COMMISSIONING)
        self.patch_rpc_methods(action.node)
        exception = self.assertRaises(NodeActionError, action.execute)
        self.assertEqual(
            get_error_message_for_exception(
                action.node.stop.side_effect),
            unicode(exception))

    def test_AbortOperation_handles_rpc_errors(self):
        action = self.make_action(
            AbortOperation, NODE_STATUS.DISK_ERASING)
        self.patch_rpc_methods(action.node)
        exception = self.assertRaises(NodeActionError, action.execute)
        self.assertEqual(
            get_error_message_for_exception(
                action.node.stop.side_effect),
            unicode(exception))

    def test_StartNode_handles_rpc_errors(self):
        action = self.make_action(StartNode, NODE_STATUS.READY)
        self.patch_rpc_methods(action.node)
        exception = self.assertRaises(NodeActionError, action.execute)
        self.assertEqual(
            get_error_message_for_exception(
                action.node.start.side_effect),
            unicode(exception))

    def test_StopNode_handles_rpc_errors(self):
        action = self.make_action(StopNode, NODE_STATUS.DEPLOYED)
        self.patch_rpc_methods(action.node)
        exception = self.assertRaises(NodeActionError, action.execute)
        self.assertEqual(
            get_error_message_for_exception(
                action.node.stop.side_effect),
            unicode(exception))

    def test_ReleaseNode_handles_rpc_errors(self):
        action = self.make_action(ReleaseNode, NODE_STATUS.ALLOCATED)
        self.patch_rpc_methods(action.node)
        exception = self.assertRaises(NodeActionError, action.execute)
        self.assertEqual(
            get_error_message_for_exception(
                action.node.stop.side_effect),
            unicode(exception))
