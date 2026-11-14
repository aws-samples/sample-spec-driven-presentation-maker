// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { cleanup } from "@testing-library/react"
import { afterEach } from "vitest"

// vitest `globals` is off, so Testing Library cannot register its own
// afterEach cleanup. Unmount everything after each test so components and
// hooks do not re-render after jsdom is torn down (#615). Node-environment
// tests (`@vitest-environment node`) render nothing, so skip them.
if (typeof document !== "undefined") {
  afterEach(() => cleanup())
}

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
