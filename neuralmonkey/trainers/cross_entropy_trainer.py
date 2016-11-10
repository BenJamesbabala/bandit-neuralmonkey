import tensorflow as tf

from neuralmonkey.logging import log

# tests: mypy

class CrossEntropyTrainer(object):
    def __init__(self, decoder, l2_regularization=0, learning_rate=1e-4):
        log("Initializing Cross-entropy trainer.")
        self.decoder = decoder
        self.learning_rate = learning_rate

        with tf.variable_scope("l2_regularization"):
            l2_value = sum([tf.reduce_sum(v ** 2) for v in tf.trainable_variables()])
            if l2_regularization > 0:
                l2_cost = l2_regularization * l2_value
            else:
                l2_cost = 0.0

            tf.scalar_summary('train_l2_cost', l2_value, collections=["summary_train"])

        optimizer = tf.train.AdamOptimizer(self.learning_rate)
        gradients = optimizer.compute_gradients(decoder.cost + l2_cost)
        #for (g, v) in gradients:
        #    if g is not None:
        #        tf.histogram_summary('gr_' + v.name, g, collections=["summary_gradients"])
        self.optimize_op = optimizer.apply_gradients(gradients, global_step=decoder.learning_step)
        #self.summary_gradients = tf.merge_summary(tf.get_collection("summary_gradients"))
        self.summary_train = tf.merge_summary(tf.get_collection("summary_train"))
        log("Trainer initialized.")

    def run(self, sess, f_dict, summary=False):
        if summary:
            _, summary_str = \
                   sess.run([self.optimize_op,
                             self.summary_train],#, self.summary_gradients
                            feed_dict=f_dict)
            return summary_str
        else:
            sess.run(self.optimize_op, feed_dict=f_dict)
