// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

class ResizeObserverStub implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver = ResizeObserverStub

class IntersectionObserverStub implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = "0px"
  readonly scrollMargin = "0px"
  readonly thresholds = [0, 0.5]
  constructor(private callback: IntersectionObserverCallback) {}
  observe(target: Element): void {
    this.callback([{
      target,
      isIntersecting: true,
      intersectionRatio: 1,
    } as IntersectionObserverEntry], this)
  }
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] { return [] }
}

globalThis.IntersectionObserver = IntersectionObserverStub
