---
title: "Convolutional neural network (Wikipedia)"
source_url: "https://en.wikipedia.org/wiki/Convolutional_neural_network"
license: "CC BY-SA 4.0"
license_url: "https://creativecommons.org/licenses/by-sa/4.0/"
type: encyclopedia
wikipedia_title: "Convolutional neural network"
wikipedia_revid: 1363769312
wikipedia_rev_timestamp: "2026-07-12T08:46:14Z"
retrieved: "2026-07-24"
---

# Convolutional neural network

> **Attribution.** This text is adapted from the English Wikipedia article
> [Convolutional neural network](https://en.wikipedia.org/wiki/Convolutional_neural_network) (revision 1363769312),
> licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Contributors: see the article history on Wikipedia. Changes: plain-text
> extract via MediaWiki API.

A convolutional neural network (CNN) is a type of feedforward neural network that learns features via filter (or kernel) optimization. This type of deep learning network has been applied to process and make predictions from many different types of data including text, images and audio. CNNs are the de-facto standard in deep learning-based approaches to computer vision and image processing, and have only recently been replaced—in some cases—by newer architectures such as the transformer.
Vanishing gradients and exploding gradients, seen during backpropagation in earlier neural networks, are prevented by the regularization that comes from using shared weights over fewer connections. For example, for each neuron in the fully-connected layer, 10,000 weights would be required for processing an image sized 100 × 100 pixels. However, applying cascaded convolution (or cross-correlation) kernels, only 25 weights for each convolutional layer are required to process 5x5-sized tiles. Higher-layer features are extracted from wider context windows, compared to lower-layer features.
Some applications of CNNs include: 

image and video recognition,
recommender systems,
image classification,
image segmentation,
medical image analysis,
natural language processing,
brain–computer interfaces, and
financial time series.
CNNs are also known as shift invariant or space invariant artificial neural networks, based on the shared-weight architecture of the convolution kernels or filters that slide along input features and provide translation-equivariant responses known as feature maps. Counter-intuitively, most convolutional neural networks are not invariant to translation, due to the downsampling operation they apply to the input.
Feedforward neural networks are usually fully connected networks, that is, each neuron in one layer is connected to all neurons in the next layer. The "full connectivity" of these networks makes them prone to overfitting data. Typical ways of regularization, or preventing overfitting, include: penalizing parameters during training (such as weight decay) or trimming connectivity (skipped connections, dropout, etc.) Robust datasets also increase the probability that CNNs will learn the generalized principles that characterize a given dataset rather than the biases of a poorly-populated set.
Convolutional networks were inspired by biological processes in that the connectivity pattern between neurons resembles the organization of the animal visual cortex. Individual cortical neurons respond to stimuli only in a restricted region of the visual field known as the receptive field. The receptive fields of different neurons partially overlap such that they cover the entire visual field.
CNNs use relatively little pre-processing compared to other image classification algorithms. This means that the network learns to optimize the filters (or kernels) through automated learning, whereas in traditional algorithms these filters are hand-engineered. This simplifies and automates the process, enhancing efficiency and scalability overcoming human-intervention bottlenecks.
