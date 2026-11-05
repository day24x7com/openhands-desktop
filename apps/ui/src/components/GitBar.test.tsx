import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GitStatus } from '@ohd/shared-types';
import { GitBar } from './GitBar';

const gitInit = vi.fn();
const gitCommit = vi.fn();
const gitBranches = vi.fn();
const gitCheckout = vi.fn();

vi.mock('../lib/api', () => ({
  api: {
    gitInit: (...args: unknown[]) => gitInit(...args),
    gitCommit: (...args: unknown[]) => gitCommit(...args),
    gitBranches: (...args: unknown[]) => gitBranches(...args),
    gitCheckout: (...args: unknown[]) => gitCheckout(...args),
  },
}));

const notARepo: GitStatus = { branch: null, entries: [], ahead: 0, behind: 0 };
const dirty: GitStatus = {
  branch: 'main',
  entries: [{ path: 'app.py', status: 'M' }],
  ahead: 0,
  behind: 0,
};

const status = (value: GitStatus) => ({ ok: true, output: '', status: value });

describe('GitBar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('offers to initialise git when the folder is not a repository', async () => {
    gitInit.mockResolvedValue(status({ ...notARepo, branch: 'main' }));
    const onChanged = vi.fn();
    render(<GitBar conversation_id="c1" status={notARepo} onChanged={onChanged} />);

    await userEvent.click(screen.getByRole('button', { name: /initialise git repository/i }));
    await waitFor(() => expect(gitInit).toHaveBeenCalledWith('c1'));
    expect(onChanged).toHaveBeenCalled();
  });

  it('shows the branch and commits a message', async () => {
    gitCommit.mockResolvedValue(status(notARepo));
    const onChanged = vi.fn();
    render(<GitBar conversation_id="c1" status={dirty} onChanged={onChanged} />);

    expect(screen.getByText('⎇ main')).toBeInTheDocument();
    expect(screen.getByText('1 changed')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Commit' }));
    await userEvent.type(screen.getByLabelText('Commit message'), 'fix: thing');
    await userEvent.click(screen.getByRole('button', { name: /commit all changes/i }));

    await waitFor(() => expect(gitCommit).toHaveBeenCalledWith('c1', 'fix: thing'));
    expect(onChanged).toHaveBeenCalled();
  });

  it('disables commit when there is nothing to commit', () => {
    render(<GitBar conversation_id="c1" status={{ ...dirty, entries: [] }} onChanged={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Commit' })).toBeDisabled();
  });

  it('surfaces git errors instead of failing silently', async () => {
    gitCommit.mockRejectedValue(new Error('nothing to commit'));
    render(<GitBar conversation_id="c1" status={dirty} onChanged={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: 'Commit' }));
    await userEvent.type(screen.getByLabelText('Commit message'), 'msg');
    await userEvent.click(screen.getByRole('button', { name: /commit all changes/i }));

    expect(await screen.findByText('nothing to commit')).toBeInTheDocument();
  });

  it('switches and creates branches', async () => {
    gitBranches.mockResolvedValue({ current: 'main', branches: ['main', 'dev'] });
    gitCheckout.mockResolvedValue(status({ ...dirty, branch: 'dev' }));
    render(<GitBar conversation_id="c1" status={dirty} onChanged={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: '⎇ main' }));
    await userEvent.click(await screen.findByRole('button', { name: 'dev' }));
    await waitFor(() => expect(gitCheckout).toHaveBeenCalledWith('c1', 'dev'));
  });
});
