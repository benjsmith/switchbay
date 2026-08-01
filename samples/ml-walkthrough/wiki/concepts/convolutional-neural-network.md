---
title: "[con] Convolutional neural network"
type: concept
created: 2026-07-24
updated: 2026-07-28
sources:
  - 20260728-231916-local-wiki-cnn.md.extracted.md
---

[[wikipedia-cnn|A feedforward network that learns features by optimizing filters]] (kernels)
(vault:20260728-231916-local-wiki-cnn.md.extracted.md). Applied to text, images and audio; the de-facto standard for
deep-learning computer vision and image processing, only recently displaced in some
cases by newer architectures such as the
[[transformer-architecture|transformer]].

**Parameter economy.** Shared weights over fewer connections regularize away the
vanishing and exploding gradients seen in earlier nets. A fully-connected neuron
needs 10,000 weights for a 100x100 image; cascaded convolution kernels need only 25
weights per convolutional layer to process 5x5 tiles. Higher layers extract
features from wider context windows than lower layers (vault:20260728-231916-local-wiki-cnn.md.extracted.md).

Also called shift- or space-invariant networks, after the shared-weight kernels
that slide along inputs producing translation-equivariant feature maps.
Counter-intuitively most CNNs are *not* translation-invariant, because of the
downsampling they apply (vault:20260728-231916-local-wiki-cnn.md.extracted.md).

Connectivity resembles the animal visual cortex: cortical neurons respond only
within a restricted receptive field, and neighbouring receptive fields overlap to
cover the visual field (vault:20260728-231916-local-wiki-cnn.md.extracted.md).

Applications include image and video recognition, recommender systems, image
classification and segmentation, medical image analysis, NLP, brain-computer
interfaces and financial time series (vault:20260728-231916-local-wiki-cnn.md.extracted.md).

Part of [[deep-learning]].
