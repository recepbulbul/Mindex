import { cva } from 'class-variance-authority'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  'relative inline-flex select-none items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-foreground font-medium text-primary-foreground shadow-[inset_0_1px_0_white,0_10px_30px_-12px_rgb(143_178_255/0.55)] hover:bg-white',
        outline:
          'border border-border-strong bg-white/[0.04] text-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.06)] backdrop-blur-md hover:border-white/25 hover:bg-white/[0.08]',
        ghost: 'text-muted-foreground hover:bg-white/[0.06] hover:text-foreground',
        destructive: 'bg-destructive text-white hover:brightness-110',
      },
      size: {
        default: 'h-9 px-3.5',
        sm: 'h-8 px-2.5 text-xs [&_svg]:size-3.5',
        icon: 'size-9',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

/** Container for a segmented control (tabs, radio groups, toggles). */
export const segmentedClass =
  'inline-flex items-center gap-0.5 rounded-xl border bg-black/25 p-1 shadow-[inset_0_1px_2px_oklch(0_0_0/0.3)]'

/** One option of a segmented control. */
export const segmentClass = (active: boolean) =>
  cn(
    'rounded-lg px-2.5 py-1 text-xs font-medium transition-all',
    active
      ? 'bg-white/[0.1] text-foreground shadow-[inset_0_1px_0_oklch(1_0_0/0.12),0_1px_3px_oklch(0_0_0/0.4)]'
      : 'text-muted-foreground hover:text-foreground',
  )
