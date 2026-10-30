import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export default function ActionMenu({
  label,
  triggerClassName,
  triggerContent,
  className,
  placement = 'bottom-end',
  children,
}: {
  label: string;
  triggerClassName: string;
  triggerContent: ReactNode;
  className: string;
  placement?: 'bottom-end' | 'top-start';
  children: (close: () => void) => ReactNode;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const focusLast = useRef(false);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    const anchor = trigger.current!.getBoundingClientRect();
    const panel = menu.current!;
    const gap = 8;
    const width = panel.offsetWidth;
    const height = panel.offsetHeight;
    const above = anchor.top - height - gap;
    const below = anchor.bottom + gap;
    const top =
      placement === 'top-start'
        ? above >= gap
          ? above
          : below
        : below + height <= window.innerHeight - gap
          ? below
          : above;
    setPosition({
      top: Math.max(gap, Math.min(top, window.innerHeight - height - gap)),
      left: Math.max(
        gap,
        Math.min(
          placement === 'top-start' ? anchor.left : anchor.right - width,
          window.innerWidth - width - gap,
        ),
      ),
    });
    const items = panel.querySelectorAll<HTMLElement>('[role="menuitem"]');
    items[focusLast.current ? items.length - 1 : 0]?.focus();
  }, [open, placement]);
  useEffect(() => {
    if (!open) return;
    const anchorAtOpen = trigger.current!.getBoundingClientRect();
    const outside = (event: PointerEvent) => {
      if (
        !menu.current?.contains(event.target as Node) &&
        !trigger.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    const dismiss = () => setOpen(false);
    const scroll = (event: Event) => {
      if (event.target instanceof Node && menu.current?.contains(event.target)) return;
      const anchor = trigger.current?.getBoundingClientRect();
      // Focusing/clicking a trigger can queue a scroll event before the menu opens.
      // Only dismiss if the anchor actually moved after positioning the menu.
      if (!anchor || anchor.top !== anchorAtOpen.top || anchor.left !== anchorAtOpen.left)
        dismiss();
    };
    document.addEventListener('pointerdown', outside);
    window.addEventListener('resize', dismiss);
    window.addEventListener('scroll', scroll, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('scroll', scroll, true);
    };
  }, [open]);
  return (
    <>
      <button
        type="button"
        className={triggerClassName}
        ref={trigger}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => {
          focusLast.current = false;
          if (open) close();
          else setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            focusLast.current = event.key === 'ArrowUp';
            setOpen(true);
          }
        }}
      >
        {triggerContent}
      </button>
      {open &&
        createPortal(
          <div
            id={id}
            className={`menu-surface action-menu ${className}`}
            role="menu"
            aria-label={label}
            ref={menu}
            style={position ?? { top: 0, left: 0, opacity: 0 }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close();
              }
              if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
                event.preventDefault();
                const items = Array.from(
                  menu.current!.querySelectorAll<HTMLElement>('[role="menuitem"]'),
                );
                const index = items.indexOf(document.activeElement as HTMLElement);
                items[
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? items.length - 1
                      : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
                ]?.focus();
              }
              // Restore the trigger before the browser advances through the page's tab order.
              if (event.key === 'Tab') close();
            }}
          >
            {children(close)}
          </div>,
          document.body,
        )}
    </>
  );
}
