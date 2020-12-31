# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from mock import Mock

from twisted.internet import defer
from twisted.trial import unittest

from buildbot.process.properties import Interpolate
from buildbot.process.results import SUCCESS
from buildbot.reporters.hipchat import HOSTED_BASE_URL
from buildbot.reporters.hipchat import HipChatStatusPush
from buildbot.test.fake import fakemaster
from buildbot.test.fake import httpclientservice as fakehttpclientservice
from buildbot.test.util.config import ConfigErrorsMixin
from buildbot.test.util.logging import LoggingMixin
from buildbot.test.util.misc import TestReactorMixin
from buildbot.test.util.reporter import ReporterTestMixin
from buildbot.test.util.warnings import assertProducesWarnings
from buildbot.warnings import DeprecatedApiWarning


class TestHipchatStatusPush(ConfigErrorsMixin, TestReactorMixin, unittest.TestCase,
                            ReporterTestMixin, LoggingMixin):

    def setUp(self):
        self.setUpTestReactor()
        self.setup_reporter_test()
        self.master = fakemaster.make_master(self, wantData=True, wantDb=True,
                                             wantMq=True)

    @defer.inlineCallbacks
    def tearDown(self):
        if self.master.running:
            yield self.master.stopService()

    @defer.inlineCallbacks
    def createReporter(self, **kwargs):
        kwargs['auth_token'] = kwargs.get('auth_token', 'abc')
        self.sp = HipChatStatusPush(**kwargs)
        self._http = yield fakehttpclientservice.HTTPClientService.getService(
            self.master, self,
            kwargs.get('endpoint', HOSTED_BASE_URL),
            debug=None, verify=None)
        yield self.sp.setServiceParent(self.master)
        yield self.master.startService()

    @defer.inlineCallbacks
    def test_authtokenTypeCheck(self):
        with self.assertRaisesConfigError('auth_token must be a string'):
            yield self.createReporter(auth_token=2)

    def test_endpointTypeCheck(self):
        with self.assertRaisesConfigError('endpoint must be a string'):
            HipChatStatusPush(auth_token="2", endpoint=2)

    @defer.inlineCallbacks
    def test_builderRoomMapTypeCheck(self):
        with self.assertRaisesConfigError('builder_room_map must be a dict'):
            yield self.createReporter(builder_room_map=2)

    @defer.inlineCallbacks
    def test_builderUserMapTypeCheck(self):
        with self.assertRaisesConfigError('builder_user_map must be a dict'):
            yield self.createReporter(builder_user_map=2)

    @defer.inlineCallbacks
    def test_interpolateAuth(self):
        yield self.createReporter(auth_token=Interpolate('auth'),
                                  builder_user_map={'Builder0': '123'})
        build = yield self.insert_build_new()
        self._http.expect(
            'post',
            '/v2/user/123/message',
            params=dict(auth_token='auth'),
            json={'message': 'Buildbot started build Builder0 here: '
                             'http://localhost:8080/#builders/79/builds/0'})
        yield self.sp._got_event(('builds', 20, 'new'), build)

    @defer.inlineCallbacks
    def test_build_started(self):
        yield self.createReporter(builder_user_map={'Builder0': '123'})
        build = yield self.insert_build_new()
        self._http.expect(
            'post',
            '/v2/user/123/message',
            params=dict(auth_token='abc'),
            json={'message': 'Buildbot started build Builder0 here: '
                             'http://localhost:8080/#builders/79/builds/0'})
        yield self.sp._got_event(('builds', 20, 'new'), build)

    @defer.inlineCallbacks
    def test_build_finished(self):
        yield self.createReporter(builder_room_map={'Builder0': '123'})
        build = yield self.insert_build_finished(SUCCESS)
        self._http.expect(
            'post',
            '/v2/room/123/notification',
            params=dict(auth_token='abc'),
            json={'message':
                  'Buildbot finished build Builder0 with result success '
                  'here: http://localhost:8080/#builders/79/builds/0'})
        yield self.sp._got_event(('builds', 20, 'finished'), build)

    @defer.inlineCallbacks
    def test_inject_extra_params(self):
        yield self.createReporter(builder_room_map={'Builder0': '123'})
        self.sp.getExtraParams = Mock()
        self.sp.getExtraParams.return_value = {'format': 'html'}
        build = yield self.insert_build_finished(SUCCESS)
        self._http.expect(
            'post',
            '/v2/room/123/notification',
            params=dict(auth_token='abc'),
            json={'message': 'Buildbot finished build Builder0 with result success '
                  'here: http://localhost:8080/#builders/79/builds/0',
                  'format': 'html'})

        yield self.sp._got_event(('builds', 20, 'finished'), build)

    @defer.inlineCallbacks
    def test_no_message_sent_without_id(self):
        yield self.createReporter()
        build = yield self.insert_build_new()
        self.sp._got_event(('builds', 20, 'new'), build)

    @defer.inlineCallbacks
    def test_private_message_sent_with_user_id(self):
        token = 'tok'
        endpoint = 'example.com'
        yield self.createReporter(auth_token=token, endpoint=endpoint)
        self.sp.getBuildDetailsAndSendMessage = Mock()
        message = {'message': 'hi'}
        postData = dict(message)
        postData.update({'id_or_email': '123'})
        self.sp.getBuildDetailsAndSendMessage.return_value = postData
        self._http.expect(
            'post',
            '/v2/user/123/message',
            params=dict(auth_token=token),
            json=message)
        self.sp.send({'complete': True})

    @defer.inlineCallbacks
    def test_room_message_sent_with_room_id(self):
        token = 'tok'
        endpoint = 'example.com'
        yield self.createReporter(auth_token=token, endpoint=endpoint)
        self.sp.getBuildDetailsAndSendMessage = Mock()
        message = {'message': 'hi'}
        postData = dict(message)
        postData.update({'room_id_or_name': '123'})
        self.sp.getBuildDetailsAndSendMessage.return_value = postData
        self._http.expect(
            'post',
            '/v2/room/123/notification',
            params=dict(auth_token=token),
            json=message)
        self.sp.send({'complete': True})

    @defer.inlineCallbacks
    def test_private_and_room_message_sent_with_both_ids(self):
        token = 'tok'
        endpoint = 'example.com'
        yield self.createReporter(auth_token=token, endpoint=endpoint)
        self.sp.getBuildDetailsAndSendMessage = Mock()
        message = {'message': 'hi'}
        postData = dict(message)
        postData.update({'room_id_or_name': '123', 'id_or_email': '456'})
        self.sp.getBuildDetailsAndSendMessage.return_value = postData
        self._http.expect(
            'post',
            '/v2/user/456/message',
            params=dict(auth_token=token),
            json=message)
        self._http.expect(
            'post',
            '/v2/room/123/notification',
            params=dict(auth_token=token),
            json=message)
        self.sp.send({'complete': True})

    @defer.inlineCallbacks
    def test_postData_values_passed_through(self):
        token = 'tok'
        endpoint = 'example.com'
        yield self.createReporter(auth_token=token, endpoint=endpoint)
        self.sp.getBuildDetailsAndSendMessage = Mock()
        message = {'message': 'hi', 'notify': True, 'message_format': 'html'}
        postData = dict(message)
        postData.update({'id_or_email': '123'})
        self.sp.getBuildDetailsAndSendMessage.return_value = postData
        self._http.expect(
            'post',
            '/v2/user/123/message',
            params=dict(auth_token=token),
            json=message)
        self.sp.send({'complete': True})

    @defer.inlineCallbacks
    def test_postData_error(self):
        token = 'tok'
        endpoint = 'example.com'
        yield self.createReporter(auth_token=token, endpoint=endpoint)
        self.sp.getBuildDetailsAndSendMessage = Mock()
        message = {'message': 'hi', 'notify': True, 'message_format': 'html'}
        postData = dict(message)
        postData.update({'id_or_email': '123'})
        self.sp.getBuildDetailsAndSendMessage.return_value = postData
        self._http.expect(
            'post',
            '/v2/user/123/message',
            params=dict(auth_token=token),
            json=message, code=404,
            content_json={
                "error_description": "This user is unknown to us",
                "error": "invalid_user"})
        self.setUpLogging()
        self.sp.send({'complete': True})
        self.assertLogged('404: unable to upload status')


class HipChatStatusPushDeprecatedSend(HipChatStatusPush):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.send_called_count = 0

    @defer.inlineCallbacks
    def send(self, build):
        self.send_called_count += 1
        yield super().send(build)


class TestHipchatStatusPushDeprecatedSend(TestReactorMixin, unittest.TestCase,
                                          ReporterTestMixin, LoggingMixin):

    def setUp(self):
        self.setUpTestReactor()
        self.setup_reporter_test()
        self.master = fakemaster.make_master(self, wantData=True, wantDb=True,
                                             wantMq=True)

    @defer.inlineCallbacks
    def tearDown(self):
        if self.master.running:
            yield self.master.stopService()

    @defer.inlineCallbacks
    def createReporter(self, **kwargs):
        kwargs['auth_token'] = kwargs.get('auth_token', 'abc')
        self.sp = HipChatStatusPushDeprecatedSend(**kwargs)
        self._http = yield fakehttpclientservice.HTTPClientService.getService(
            self.master, self,
            kwargs.get('endpoint', HOSTED_BASE_URL),
            debug=None, verify=None)
        yield self.sp.setServiceParent(self.master)
        yield self.master.startService()

    @defer.inlineCallbacks
    def test_build_started(self):
        yield self.createReporter(builder_user_map={'Builder0': '123'})
        build = yield self.insert_build_new()
        self._http.expect(
            'post',
            '/v2/user/123/message',
            params=dict(auth_token='abc'),
            json={'message': 'Buildbot started build Builder0 here: '
                             'http://localhost:8080/#builders/79/builds/0'})
        with assertProducesWarnings(DeprecatedApiWarning,
                                    message_pattern='send\\(\\) in reporters has been deprecated'):
            yield self.sp._got_event(('builds', 20, 'new'), build)
        self.assertEqual(self.sp.send_called_count, 1)
