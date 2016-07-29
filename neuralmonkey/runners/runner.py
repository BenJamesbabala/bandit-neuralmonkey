import tensorflow as tf

from neuralmonkey.learning_utils import feed_dicts
from neuralmonkey.logging import debug

# tests: lint, mypy

# pylint: disable=too-few-public-methods
class GreedyRunner(object):
    def __init__(self, decoder, batch_size):
        self.decoder = decoder
        self.batch_size = batch_size
        self.vocabulary = decoder.vocabulary

    def __call__(self, sess, dataset, coders):
        batched_dataset = dataset.batch_dataset(self.batch_size)
        decoded_sentences = []

        # if are are target sentence, we will compute also the
        # losses, otherwise just compute zero
        if dataset.has_series(self.decoder.data_id):
            losses = [self.decoder.train_loss,
                      self.decoder.runtime_loss]
        else:
            losses = [tf.zeros([]), tf.zeros([])]

        loss_with_gt_ins = 0.0
        loss_with_decoded_ins = 0.0
        batch_count = 0
        for batch in batched_dataset:
            batch_feed_dict = feed_dicts(batch, coders, train=False)
            batch_count += 1
            if dataset.has_series(self.decoder.data_id):
                losses = [self.decoder.train_loss,
                          self.decoder.runtime_loss]
            else:
                losses = [tf.zeros([]), tf.zeros([])]

            computation = sess.run(losses
                                   + [self.decoder.decoded_logprobs]
                                   + self.decoder.decoded,
                                   feed_dict=batch_feed_dict)
            loss_with_gt_ins += computation[0]
            loss_with_decoded_ins += computation[1]

            logprobs = computation[2]
            debug("log probability of the first sentence in batch: {}".
                  format(logprobs[0]), label="dumper")

            decoded_sentences_batch = \
                    self.vocabulary.vectors_to_sentences(computation[3:])
            decoded_sentences += decoded_sentences_batch

        return decoded_sentences, \
               loss_with_gt_ins / batch_count, \
               loss_with_decoded_ins / batch_count
