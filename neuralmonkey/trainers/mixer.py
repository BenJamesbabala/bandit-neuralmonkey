import tensorflow as tf

from neuralmonkey.logging import log
from neuralmonkey.evaluators.bleu import BLEUEvaluator

# tests: mypy
# TODO refactor to have the same API as cross-entropy trainer

class Mixer(object):
    """

    This trainer is implementation of the Sequence Level Training with
    Recurrent Neural Networks by Ranzato et al.
    (http://arxiv.org/abs/1511.06732). It trains the translation for a given
    number of epoch using the standard cross-entropy loss and then it gradually
    starts to use the reinforce algorithm for the optimization.

    """
    def __init__(self, decoder, initial_trainer, xent_calls, moving_calls, learning_rate):
        """
        Constructs the TensorFlow graph for the MIXER code - i.e. the regressor
        estimating BLEU from hidden states and the gradients from the REINFORCE
        algorithm.

        Args:

            decoder: Decoder.

            xent_calls: The number minibatches for which the standard
                crossentropy learning will be used.

            moving_calls: Number of minibatches after which the algorithm will
                proceed to use the REINFORCE algorithm for a longer suffix of the
                senntences.

        """
        # TODO L2 regularization
        # TODO plot gradients
        self.xent_trainer = initial_trainer
        self.decoder = decoder
        self.called = 0
        self.xent_calls = xent_calls
        self.moving_calls = moving_calls
        self.learning_rate = learning_rate

        with tf.variable_scope('mixer'):
            # BLEU score needs to be computed outside the TF
            self.bleu = tf.placeholder(tf.float32, [None])

            hidden_states = decoder.train_rnn_outputs  # with monster_decoder: decoder.hidden_states

            # a simple regressor that estimates the BLEU score from the network's hidden states
            with tf.variable_scope('exprected_reward_regressor'):
                linear_reg_W = tf.Variable(tf.truncated_normal([decoder.rnn_size, 1]))
                linear_reg_b = tf.Variable(tf.zeros([1]))

                expected_rewards = [
                    tf.squeeze(tf.matmul(h, linear_reg_W)) + linear_reg_b for h in hidden_states]

                regression_loss = sum([(r - self.bleu) ** 2 for r in expected_rewards]) * 0.5
                self.regression_optimizer = tf.train.AdamOptimizer(self.learning_rate).minimize(regression_loss)


            ## decoded_logits: list of [batch x vabulary] tensors (length max sequence)
            ## decoded_seq: list of [batch x 1] tensors (length sequence) --
            ##   contains vocabulary indices (argmaxs)
            with tf.variable_scope("reinforce_gradients"):
                # this is a dirty trick to get the indices of maxima in the logits
                max_logits = \
                    [tf.expand_dims(tf.reduce_max(l, 1), 1) \
                        for l in decoder.train_logits] ## batch x 1 x 1  
                indicator = \
                    [tf.to_float(tf.equal(ml, l)) \
                        for ml, l in zip(max_logits, decoder.train_logits)] ## batch x slovnik

                log("Forward computation graph ready")

                # this is implementation of equation (11) in the paper
                derivatives = [
                    tf.reduce_sum(
                        tf.expand_dims(self.bleu - r, 1) * (tf.nn.softmax(l) - i) * w,
                        0, keep_dims=True)
                    for r, l, i, w in zip(
                        expected_rewards, decoder.train_logits, indicator, decoder.train_weights)]
                ## ^^^ list of  [1 x vocabulary] tensors

                # this derivatives are constant for us now, we don't really
                # want to propagate the dradient back to this computaiton
                derivatives_stopped = [tf.stop_gradient(d) for d in derivatives]

                # we must train the regressor independently
                trainable_vars = \
                    [v for v in tf.trainable_variables() if not v.name.startswith('mixer')]

                # this is implementation of equation (10) in the paper
                reinforce_gradients = \
                    [tf.gradients(l * d, trainable_vars) \
                        for l, d in zip(decoder.train_logits, derivatives_stopped)]
                ## ^^^ [slovnik x shape promenny](delky max seq)

                log("Reinforce gradients computed")

            with tf.variable_scope("cross_entropy_gradients"):
                cross_entropies = [
                    tf.reduce_sum(tf.nn.sparse_softmax_cross_entropy_with_logits(l, t) * w, 0)
                    for l, t, w in zip(decoder.train_logits, decoder.train_targets, decoder.train_weights)
                ]
                    ## ^^^ list of scalars in time

                xent_gradients = [tf.gradients(e, trainable_vars) for e in cross_entropies]
                log("Cross-entropy gradients computed")

            self.mixer_weights_plc = [tf.placeholder(tf.float32, []) for _ in hidden_states]

            mixed_gradients = [] # a list for each of the traininable variables

            for i, (rgs, xent_gs, mix_w) in enumerate(
                    zip(reinforce_gradients, xent_gradients, self.mixer_weights_plc)):
                for j, (rg, xent_g) in enumerate(zip(rgs, xent_gs)):
                    if xent_g is None and i == 0:
                        mixed_gradients.append(None)
                        continue

                    if type(xent_g) == tf.Tensor or type(xent_g) == tf.IndexedSlices:
                        g = tf.add(tf.scalar_mul(mix_w, xent_g), tf.scalar_mul(1 - mix_w, rg))
                    elif xent_g is None:
                        continue
                    else:
                        raise Exception("Unnkown type of gradients: {}".format(type(xg)))

                    if i == 0:
                        mixed_gradients.append(g)
                    else:
                        if mixed_gradients[j] is None:
                            mixed_gradients[j] = g
                        else:
                            mixed_gradients[j] += g

            self.mixer_optimizer = \
                    tf.train.AdamOptimizer(self.learning_rate).apply_gradients(list(zip(mixed_gradients, trainable_vars)))

        #self.summary_gradients = tf.merge_summary(tf.get_collection("summary_gradients"))
        self.summary_train = summary_train = tf.merge_summary(tf.get_collection("summary_train"))

        ### WHAAAT??? tenhle kod tu nechavam zakomentovanej z piety
        ##self.summary_val = summary_train = tf.merge_summary(tf.get_collection("summary_val"))

    def run(self, sess, fd, references, verbose=False):
        self.called += 1
        if self.called < self.xent_calls:
            return self.xent_trainer.run(sess, fd, references, verbose=verbose)

        reinforce_steps = max(self.decoder.max_output + 2, (self.called - self.xent_calls) / self.moving_calls + 1)

        decoded_sequence = sess.run(self.decoder.decoded, feed_dict=fd)
        sentences = self.decoder.vocabulary.vectors_to_sentences(decoded_sequence)

        def get_bleu(r, s):
            # sentence BLEU crashes in case of empty sentences
            if not s:
                return 0.0
            else:
                ## TODO think about what this should be - BLEU over one sentence
                ## seems weird.
                return BLEUEvaluator.bleu([s], [[r]], ngrams=1)

        bleus = [get_bleu(r, s) for r, s in zip(references, sentences)]


        fd[self.bleu] = bleus

        for i, w_plc in enumerate(reversed(self.mixer_weights_plc)):
            if i <= reinforce_steps:
                fd[w_plc] = 0.0
            else:
                fd[w_plc] = 1.0

        if verbose:
            computation = sess.run(
                [self.mixer_optimizer, self.decoder.runtime_loss,
                 self.decoder.train_loss, self.summary_train]
                + self.decoder.decoded,
                feed_dict=fd)
        else:
            computation = sess.run([self.mixer_optimizer], feed_dict=fd)

        sess.run(self.regression_optimizer, feed_dict=fd)

        return computation
