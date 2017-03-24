from typing import Any, List
from neuralmonkey.trainers.generic_bandit_trainer import GenericBanditTrainer, \
    BanditObjective, _clip_probs

import tensorflow as tf

# tests; pylint,mypy


def exploit_only_objective(decoder, initial_temperature) -> BanditObjective:
    """Get exploit only objective from decoder."""
    decoded_logprobs = tf.expand_dims(
        tf.expand_dims(
            tf.reduce_sum(
                tf.pack(decoder.decoded_logprobs), [0]),
            0),
        1)
    decoded = tf.expand_dims(tf.pack(decoder.decoded), 2)
    decoder.neg_sample_ix = tf.constant(-1)  # not used but must be set for fetches
    return BanditObjective(
        name="{} - exploit_only".format(decoder.name),
        decoder=decoder,
        samples=decoded,  # greedy output
        sample_logprobs=decoded_logprobs,
        loss=tf.reduce_mean(tf.mul(decoded_logprobs, -decoder.rewards),
                             [0, 1]),
        gradients=lambda grad_fun: grad_fun(
            tf.reduce_mean(  # mean gradient of batch and samples
                            decoded_logprobs *  # score function
                            tf.stop_gradient(  # don't differentiate this
                                            # loss from user feedback
                                            -(decoder.rewards - decoder.baseline)
                                            + # entropy regularizer T*(log p +1)
                                            # T is annealed
                                            _get_temperature(
                                                initial_temperature,
                                                decoder.epoch)
                                            * (decoded_logprobs + 1)
                            )
            )
        )
    )

def expected_loss_objective(decoder, initial_temperature) -> BanditObjective:
    """Get expected loss objective from decoder."""
    sample_ids, sample_logprobs, _ = _get_samples(decoder, neg=False)
    decoder.neg_sample_ix = tf.constant(-1)  # not used but needed for outputs
    return BanditObjective(
        name="{} - expected_loss".format(decoder.name),
        decoder=decoder,
        samples=sample_ids,
        sample_logprobs=sample_logprobs,
        loss=tf.reduce_mean(tf.mul(tf.exp(sample_logprobs), -decoder.rewards),
                             [0, 1]),
        # TODO include entropy in loss
        gradients=lambda grad_fun: grad_fun(
            tf.reduce_mean(  # mean gradient of batch and samples
                            sample_logprobs *  # score function
                            tf.stop_gradient(  # don't differentiate this
                                            # loss from user feedback
                                            -(decoder.rewards-decoder.baseline)
                                            + # entropy regularizer T*(log p +1)
                                            # T is annealed
                                            _get_temperature(
                                                initial_temperature,
                                                decoder.epoch)
                                            * (sample_logprobs + 1)

                            )
            )
        )
    )


def cross_entropy_objective(decoder, initial_temperature, clip_prob, factor) \
        -> BanditObjective:
    """Get bandit cross-entropy loss objective from decoder."""
    sample_ids, sample_logprobs, _ = _get_samples(decoder, neg=False)
    decoder.neg_sample_ix = tf.constant(-1)  # not used but needed for outputs
    return BanditObjective(
        name="{} - cross-entropy".format(decoder.name),
        decoder=decoder,
        samples=sample_ids,
        sample_logprobs=sample_logprobs,
        loss=-tf.reduce_mean(tf.mul(sample_logprobs, decoder.rewards),
                             [0, 1]),
        gradients=lambda grad_fun: grad_fun(
            tf.reduce_mean(   # mean gradient of batch and samples
                -sample_logprobs *  # score function
                tf.stop_gradient(  # don't differentiate this
                                ( (decoder.rewards-decoder.baseline) -
                                 # entropy regularizer T*(log p +1)
                                 # T is annealed
                                 _get_temperature(
                                     initial_temperature,
                                     decoder.epoch)
                                 * (sample_logprobs + 1))
                                /  # divide by factor * clipped sample prob
                                (factor*
                                 _clip_probs(tf.exp(sample_logprobs), clip_prob))
                )
            )
        )
    )


def pairwise_objective(decoder, initial_temperature) -> BanditObjective:
    """Get bandit cross-entropy loss objective from decoder."""
    #sample_ids, sample_logprobs, _ = _get_samples(decoder, neg=False)
    #sample_ids_2, sample_logprobs_2, neg_ix = _get_samples(decoder, neg=True)
    sample_ids, sample_ids_2, sample_logprobs, sample_logprobs_2, neg_ix = \
        _get_sample_pairs(decoder)
    pair_logprobs = (sample_logprobs + sample_logprobs_2)
    decoder.neg_sample_ix = neg_ix

    return BanditObjective(
        name="{} - pairwise".format(decoder.name),
        decoder=decoder,
        samples=[sample_ids, sample_ids_2],
        sample_logprobs=[sample_logprobs, sample_logprobs_2],
        loss=tf.reduce_mean(tf.mul(tf.exp(pair_logprobs), -(1-decoder.rewards)),
                             [0, 1]),
        gradients=lambda grad_fun: grad_fun(
            tf.reduce_mean(  # mean gradient of batch and samples
                pair_logprobs *  # score function
                tf.stop_gradient(  # don't differentiate this
                    # loss from user feedback
                    -(1-decoder.rewards) +
                    # entropy regularizer T*(log p +1)
                    # T is annealed
                    _get_temperature(
                        initial_temperature,
                        decoder.epoch)
                    * (pair_logprobs + 1)
                )
            )
        )
    )


def pairwise_xent_objective(decoder, initial_temperature, clip_prob, factor) \
        -> BanditObjective:
    """Get bandit cross-entropy loss objective from decoder."""
    sample_ids, sample_ids_2, sample_logprobs, sample_logprobs_2, neg_ix = \
        _get_sample_pairs_from_runtime_logits(decoder)
    pair_logprobs = (sample_logprobs + sample_logprobs_2)
    decoder.neg_sample_ix = neg_ix

    pair_logprobs = (sample_logprobs + sample_logprobs_2)
    pair_probs = tf.exp(pair_logprobs)

    return BanditObjective(
        name="{} - pairwise_xent".format(decoder.name),
        decoder=decoder,
        samples=[decoder.sample_ids, decoder.sample_ids_2],
        sample_logprobs=[decoder.sample_logprobs,
                         decoder.sample_logprobs_2],
        loss=-tf.reduce_mean(tf.mul(pair_logprobs,
                                    decoder.rewards), [0, 1]),
        gradients=lambda grad_fun: grad_fun(
            tf.reduce_mean(  # mean gradient of batch and samples
                -pair_logprobs *  # score function
                tf.stop_gradient(  # don't differentiate this
                    (decoder.rewards -
                     # entropy regularizer T*(log p +1)
                     # T is annealed
                     _get_temperature(
                         initial_temperature,
                         decoder.epoch)
                     * (pair_logprobs + 1))
                    /  # divide by factor * clipped sample prob
                    (factor *
                     _clip_probs(pair_probs, clip_prob))
                )
            )
        )
    )


def _get_temperature(initial_temperature, current_epoch):
    """
    Annealing temperature with decay function as in ACL paper:
    T = T0 / ((epoch + 1)^1/3)
    :param initial_temperature:
    :param current_epoch:
    :return:
    """
    return initial_temperature/((tf.cast(current_epoch, tf.float32)+1)**1/3.)


def _get_samples(decoder, neg=False):
    tf.get_variable_scope().reuse_variables()
    sample_mode = decoder.sample_size
    # TODO so far only one sample
    if neg:
        sample_mode *= -1
    _, _, sample_ids, sample_logprob, _, neg_ix = \
        decoder._attention_decoder(
            decoder.embedded_go_symbols,
            attention_on_input=decoder.attention_on_input,
            train_mode=False,
            sample_mode=sample_mode,
            temperature=decoder.temperature,
            scope="{}/attention_decoder".format(decoder.name))
    # expansion is necessary for generalization of processing of multiple samples
    sample_ids = tf.expand_dims(tf.pack(sample_ids), 2)  # time x batch x sample_size
    sample_logprobs = tf.expand_dims(sample_logprob, 1) # batch x sample_size
    return sample_ids, sample_logprobs, neg_ix

def _get_sample_pairs(decoder):
    sample_ids, sample_logprobs, neg_ix = _get_samples(decoder, neg=False)
    greedy_logprobs = tf.expand_dims(
        tf.expand_dims(
            tf.reduce_sum(
                tf.pack(decoder.decoded_logprobs), [0]),
            0),
        1)
    greedy_ids = tf.expand_dims(tf.pack(decoder.decoded), 2)
    return greedy_ids, sample_ids, greedy_logprobs, sample_logprobs, neg_ix

def _get_sample_pairs_from_runtime_logits(decoder):
    """Sample from runtime logits"""
    sample_ids, sample_logprob, _ = decoder._sample_from_runtime_logits(neg=False)
    sample_ids2, sample_logprob2, neg_ix = decoder._sample_from_runtime_logits(neg=True)
    sample_ids = tf.expand_dims(tf.pack(sample_ids),
                                2)  # time x batch x sample_size
    sample_logprobs = tf.expand_dims(sample_logprob, 1)  # batch x sample_size
    sample_ids2 = tf.expand_dims(tf.pack(sample_ids2),
                                2)  # time x batch x sample_size
    sample_logprobs2 = tf.expand_dims(sample_logprob2, 1)  # batch x sample_size
    return sample_ids, sample_ids2, sample_logprobs, sample_logprobs2, neg_ix


class ExploitOnlyTrainer(GenericBanditTrainer):
    def __init__(self, decoders: List[Any], evaluator, l1_weight=0.,
                 l2_weight=0., initial_temperature=0., clip_norm=False,
                 optimizer=None, binary_feedback=False, store_gradients=False, baseline=False) -> None:
        self.store_gradients = store_gradients
        initial_temperature = initial_temperature
        objective = exploit_only_objective(decoders[0],
                                            initial_temperature=initial_temperature)
        super(ExploitOnlyTrainer, self).__init__(
            objective, evaluator, l1_weight, l2_weight,
            clip_norm=clip_norm,
            optimizer=optimizer, pairwise=False,
            binary_feedback=binary_feedback, store_gradients=store_gradients, baseline=baseline)


class ExpectedLossTrainer(GenericBanditTrainer):
    def __init__(self, decoders: List[Any], evaluator, l1_weight=0.,
                 l2_weight=0., initial_temperature=0., clip_norm=False,
                 optimizer=None, binary_feedback=False, store_gradients=False, baseline=False) -> None:
        initial_temperature = initial_temperature
        self.store_gradients = store_gradients
        objective = expected_loss_objective(decoders[0],
                                            initial_temperature=initial_temperature)
        super(ExpectedLossTrainer, self).__init__(
            objective, evaluator, l1_weight, l2_weight,
            clip_norm=clip_norm,
            optimizer=optimizer, pairwise=False,
            binary_feedback=binary_feedback, store_gradients=store_gradients, baseline=baseline)


class CrossEntropyTrainer(GenericBanditTrainer):
    def __init__(self, decoders: List[Any], evaluator, l1_weight=0.,
                 l2_weight=0., initial_temperature=0., clip_norm=False,
                 optimizer=None, binary_feedback=False,
                 clip_prob=0.0, factor=1.0e10, store_gradients=False, baseline=False) -> None:
        self.store_gradients = store_gradients
        objective = cross_entropy_objective(decoders[0],
                                            initial_temperature=initial_temperature,
                                            clip_prob=clip_prob,
                                            factor=factor)
        super(CrossEntropyTrainer, self).__init__(
            objective, evaluator, l1_weight, l2_weight,
            clip_norm=clip_norm,
            optimizer=optimizer, pairwise=False,
            binary_feedback=binary_feedback, store_gradients=store_gradients, baseline=baseline)


class PairwiseTrainer(GenericBanditTrainer):
    def __init__(self, decoders: List[Any], evaluator, l1_weight=0.,
                 l2_weight=0., initial_temperature=0., clip_norm=False,
                 optimizer=None, binary_feedback=False, store_gradients=False, baseline=False) -> None:
        self.store_gradients = store_gradients
        objective = pairwise_objective(decoders[0],
                                       initial_temperature=initial_temperature)
        super(PairwiseTrainer, self).__init__(
            objective, evaluator, l1_weight, l2_weight, clip_norm=clip_norm,
            optimizer=optimizer, pairwise=True, binary_feedback=binary_feedback, store_gradients=store_gradients, baseline=baseline)


class PairwiseXentTrainer(GenericBanditTrainer):
    def __init__(self, decoders: List[Any], evaluator, l1_weight=0.,
                 l2_weight=0., initial_temperature=0., clip_norm=False,
                 optimizer=None, binary_feedback=False,
                 clip_prob=0., factor=1.0e-10, store_gradients=False, baseline=False) -> None:
        self.store_gradients = store_gradients
        objective = pairwise_xent_objective(decoders[0],
                                            initial_temperature=initial_temperature,
                                            clip_prob=clip_prob,
                                            factor=factor)
        super(PairwiseXentTrainer, self).__init__(
            objective, evaluator, l1_weight, l2_weight,
            clip_norm=clip_norm,
            optimizer=optimizer, pairwise=True, binary_feedback=binary_feedback, store_gradients=store_gradients, baseline=baseline)
