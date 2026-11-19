// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Collapse — keeps its children while they fold away (height and opacity to zero), then
 * removes them. Showing them again is immediate.
 */

"use client"

import { type ReactNode, useLayoutEffect, useRef, useState } from "react"
import { collapseHeight } from "@/lib/motion"

interface CollapseProps {
  show: boolean
  children: ReactNode
  className?: string
}

export function Collapse({ show, children, className }: CollapseProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [mounted, setMounted] = useState(show)
  const animRef = useRef<Animation | null>(null)

  useLayoutEffect(() => {
    if (show) {
      animRef.current?.cancel()
      animRef.current = null
      if (ref.current) ref.current.style.overflow = ""
      setMounted(true)
      return
    }
    const anim = ref.current ? collapseHeight(ref.current) : null
    if (!anim) { setMounted(false); return }
    animRef.current = anim
    anim.finished.then(() => { if (animRef.current === anim) setMounted(false) }).catch(() => {})
  }, [show])

  if (!mounted) return null
  // flex-none: inside a column that fills its height, the block would otherwise be squeezed to nothing at once.
  return <div ref={ref} className={`flex-none ${className ?? ""}`} aria-hidden={show ? undefined : true}>{children}</div>
}
