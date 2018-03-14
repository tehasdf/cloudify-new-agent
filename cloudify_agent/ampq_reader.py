#!/usr/bin/env python
########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
############

import argparse
import json
import logging
import ssl
import time
import sys

from cloudify import dispatch
import pika
from pika.exceptions import AMQPConnectionError

D_CONN_ATTEMPTS = 12
D_RETRY_DELAY = 5
BATCH_SIZE = 100
MAX_BATCH_DELAY = 5
BROKER_PORT_SSL = 5671
BROKER_PORT_NO_SSL = 5672


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')  # NOQA
ch.setFormatter(formatter)
logger.addHandler(ch)


class AMQPTopicConsumer(object):

    def __init__(self,
                 queue,
                 routing_key,
                 connection_parameters=None):
        """
            AMQPTopicConsumer initialisation expects a connection_parameters
            dict as provided by the __main__ of amqp_influx.
        """
        self.queue = queue
        self.result_exchange = '{0}_result'.format(queue)
        if connection_parameters is None:
            connection_parameters = {}

        credentials = connection_parameters.get('credentials', {})
        credentials_object = pika.credentials.PlainCredentials(
            # These may be passed as None, so handle the default outside of
            # the get
            username=credentials.get('username') or 'guest',
            password=credentials.get('password') or 'guest',
        )
        connection_parameters['credentials'] = credentials_object

        if connection_parameters.get('ssl', False):
            connection_parameters['ssl_options'] = {
                'cert_reqs': ssl.CERT_REQUIRED,
                # Currently, not having a ca path with SSL enabled is
                # effectively an error, so we will let it fail
                'ca_certs': connection_parameters['ca_path'],
            }

        if 'ca_path' in connection_parameters.keys():
            # We don't need this any more
            connection_parameters.pop('ca_path')

        # add retry with try/catch because Pika currently ignoring these
        # connection parameters when using BlockingConnection:
        # https://github.com/pika/pika/issues/354
        attempts = connection_parameters.get('connection_attempts',
                                             D_CONN_ATTEMPTS)
        timeout = connection_parameters.get('retry_delay', D_RETRY_DELAY)
        for _ in range(attempts):
            try:
                self.connection = pika.BlockingConnection(
                    pika.ConnectionParameters(**connection_parameters))
            except AMQPConnectionError:
                time.sleep(timeout)
            else:
                break
        else:
            raise AMQPConnectionError

        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=queue,
                                   # type='direct',
                                   durable=True,
                                   auto_delete=False)
        self.channel.exchange_declare(
            exchange=self.result_exchange,
            type='direct',
            auto_delete=False,
            durable=True)
        # result = self.channel.queue_declare(
        #     auto_delete=True,
        #     durable=False,
        #     exclusive=False)
        # queue = result.method.queue
        # self.channel.queue_bind(queue=queue,
        #                         queue=queue,
        #                         routing_key=routing_key)
        self.channel.basic_consume(self._process, queue)

    def consume(self):
        self.channel.start_consuming()

    def _process(self, channel, method, properties, body):
        with open('/tmp/bla', 'ab') as f:
            f.write(body)
            f.write('\n########\n')
        parsed_body = json.loads(body)
        logger.info(parsed_body)
        try:
            task = parsed_body['cloudify_task']
            kwargs = task['kwargs']
            rv = dispatch.dispatch(**kwargs)
            result = {'ok': True, 'id': parsed_body['id'], 'result': rv}
        except Exception as e:
            logger.warn('Failed message processing: {0!r}'.format(e))
            logger.warn('Body: {0}\nType: {1}'.format(body, type(body)))
            result = {'ok': False, 'error': repr(e), 'id': parsed_body['id']}
        finally:
            logger.info('response %r', result)
            self.channel.basic_publish(
                self.result_exchange, '', json.dumps(result))
            self.channel.basic_ack(method.delivery_tag)


def main(args):
    conn_params = {
        'host': args.host,
        'port': 5671,
        'connection_attempts': 12,
        'virtual_host': args.vhost,
        'retry_delay': 5,
        'credentials': {
            'username': args.username,
            'password': args.password,
        },
        'ca_path': '/etc/cloudify/ssl/cloudify_internal_ca_cert.pem',
        'ssl': True,
    }

    consumer = AMQPTopicConsumer(
        queue=args.name,
        routing_key='*',
        connection_parameters=conn_params)
    consumer.consume()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='172.20.0.2')
    parser.add_argument('--username',
                        default='rabbitmq_user_default_tenant')
    parser.add_argument('--password',
                        default='vbIkmDx3CXFNAdst_pj6a4DFmzYT2PPP')
    parser.add_argument('--name', default='vm_5ngcet')
    parser.add_argument('--vhost', default='rabbitmq_vhost_default_tenant')
    args = parser.parse_args()
    main(args)
