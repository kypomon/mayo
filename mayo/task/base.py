import collections
from contextlib import contextmanager

import tensorflow as tf

from mayo.log import log
from mayo.error import NotImplementedError
from mayo.net.tf import TFNet
from mayo.session.test import Test


class TFTaskBase(object):
    """Specifies common training and evaluation tasks.  """
    def __init__(self, session):
        super().__init__()
        self.is_test = isinstance(session, Test)
        self.session = session
        self.config = session.config
        self.num_gpus = self.config.system.num_gpus
        self.mode = session.mode
        self.estimator = session.estimator
        self._instantiate_nets()

    @contextmanager
    def _gpu_context(self, gid):
        with tf.device('/gpu:{}'.format(gid)):
            with tf.name_scope('tower_{}'.format(gid)) as scope:
                yield scope

    def map(self, func):
        iterer = enumerate(zip(self.nets, self.predictions, self.truths))
        for i, (net, prediction, truth) in iterer:
            with self._gpu_context(i):
                yield func(net, prediction, truth)

    def _instantiate_nets(self):
        nets = []
        inputs = []
        predictions = []
        truths = []
        names = []
        model = self.config.model
        if self.is_test:
            folder = self.config.system.search_path.run.inputs[0]
            iterer = self.augment(folder)
        else:
            iterer = self.generate()
        for i, (data, additional) in enumerate(iterer):
            if self.is_test:
                name, truth = additional, None
            else:
                name, truth = None, additional
            log.debug('Instantiating graph for GPU #{}...'.format(i))
            with self._gpu_context(i):
                net = TFNet(self.session, model, data, bool(nets))
            nets.append(net)
            prediction = net.outputs()
            data, prediction, truth = self.transform(
                net, data, prediction, truth)
            if i == 0:
                self._register_estimates(prediction, truth)
            inputs.append(data)
            predictions.append(prediction)
            truths.append(truth)
            names.append(name)
        self.nets = nets
        self.inputs = inputs
        self.predictions = predictions
        self.truths = truths
        self.names = names

    def _register_estimates(self, prediction, truth):
        def register(root, mapping):
            history = 'infinite' if self.mode == 'validate' else None
            if not isinstance(mapping, collections.Mapping):
                self.estimator.register(mapping, root, history=history)
                return
            for key, value in mapping.items():
                register(value, '{}.{}'.format(root, key))
        register('prediction', prediction)
        register('truth', truth)

    def transform(self, net, data, prediction, truth):
        return data, prediction, truth

    def generate(self):
        raise NotImplementedError(
            'Please implement .generate() which produces training/validation '
            'samples and the expected truth results.')

    def augment(self, serialized):
        raise NotImplementedError(
            'Please implement .augment() which augments input tensors.')

    def train(self, net, prediction, truth):
        raise NotImplementedError(
            'Please implement .train() which returns the loss tensor.')

    def eval(self, net, prediction, truth):
        raise NotImplementedError(
            'Please implement .eval() which returns the evaluation metrics.')

    def test(self, name, inputs, prediction):
        raise NotImplementedError(
            'Please implement .test() which produces human-readable output '
            'for a given input.')

    def map_train(self):
        return list(self.map(self.train))

    def map_eval(self):
        return list(self.map(self.eval))