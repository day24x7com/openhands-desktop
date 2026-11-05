import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ConversationEvent } from '@ohd/shared-types';
import { ApprovalDialog } from './Panels';
import { Timeline } from './Timeline';

const base = { id: 1, conversation_id: 'c1', seq: 1, ts: '2026-01-01T00:00:00Z' };

describe('Timeline', () => {
  it('shows an empty state when there are no events', () => {
    render(<Timeline events={[]} />);
    expect(screen.getByText(/describe a task/i)).toBeDefined();
  });

  it('renders user and assistant messages', () => {
    const events: ConversationEvent[] = [
      { ...base, type: 'message', role: 'user', content: 'Add a health endpoint' },
      { ...base, id: 2, seq: 2, type: 'message', role: 'assistant', content: 'On it.' },
    ];
    render(<Timeline events={events} />);
    expect(screen.getByText('Add a health endpoint')).toBeDefined();
    expect(screen.getByText('On it.')).toBeDefined();
  });

  it('renders action cards that expand to show arguments', async () => {
    const events: ConversationEvent[] = [
      {
        ...base,
        type: 'action',
        tool: 'run_shell',
        call_id: 'call-1',
        summary: 'npm test',
        args: { command: 'npm test' },
      },
    ];
    render(<Timeline events={events} />);
    const button = screen.getByRole('button', { expanded: false });
    await userEvent.click(button);
    expect(screen.getByText(/"command": "npm test"/)).toBeDefined();
  });

  it('renders the latest plan only', () => {
    const events: ConversationEvent[] = [
      { ...base, type: 'plan', items: [{ title: 'old step', status: 'todo' }] },
      { ...base, id: 2, seq: 2, type: 'plan', items: [{ title: 'write tests', status: 'in_progress' }] },
    ];
    render(<Timeline events={events} />);
    expect(screen.queryByText('old step')).toBeNull();
    expect(screen.getByText('write tests')).toBeDefined();
  });

  it('surfaces errors', () => {
    const events: ConversationEvent[] = [
      { ...base, type: 'error', message: 'Authentication failed (401)', recoverable: true },
    ];
    render(<Timeline events={events} onRetry={() => undefined} />);
    expect(screen.getByText(/Authentication failed/)).toBeDefined();
  });
});

describe('ApprovalDialog', () => {
  it('reports approve and deny decisions', async () => {
    const onDecide = vi.fn();
    render(<ApprovalDialog summary="rmdir /s /q data" reason="recursive directory delete" onDecide={onDecide} />);
    expect(screen.getByText(/recursive directory delete/)).toBeDefined();
    await userEvent.click(screen.getByRole('button', { name: /approve/i }));
    expect(onDecide).toHaveBeenCalledWith(true, false);
    await userEvent.click(screen.getByRole('button', { name: /deny/i }));
    expect(onDecide).toHaveBeenCalledWith(false, false);
  });
});
