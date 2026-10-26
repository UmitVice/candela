package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"sort"
	"sync"
	"syscall"
	"time"
)

const (
	maxLogBytes  = 20 << 20
	stableAfter  = 2 * time.Minute
	maxBackoff   = time.Minute
	sandboxExec  = "/usr/bin/sandbox-exec"
	childPATH    = "/usr/bin:/bin:/usr/sbin:/sbin"
	childLang    = "en_US.UTF-8"
	killFallback = 5 * time.Second
)

type child struct {
	name    string
	bin     string
	args    []string
	env     map[string]string
	profile string
	params  map[string]string
	dir     string
	logPath string
	stopIn  time.Duration
	log     *slog.Logger

	mu  sync.Mutex
	cmd *exec.Cmd
}

func (c *child) argv() (string, []string) {
	if c.profile == "" {
		return c.bin, c.args
	}
	args := []string{"-f", c.profile}
	keys := make([]string, 0, len(c.params))
	for k := range c.params {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		args = append(args, "-D", k+"="+c.params[k])
	}
	return sandboxExec, append(append(args, c.bin), c.args...)
}

func rotate(path string) {
	if st, err := os.Stat(path); err == nil && st.Size() > maxLogBytes {
		_ = os.Rename(path, path+".1")
	}
}

func (c *child) start() (*exec.Cmd, error) {
	rotate(c.logPath)
	out, err := os.OpenFile(c.logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return nil, err
	}
	defer out.Close()
	name, args := c.argv()
	cmd := exec.Command(name, args...) //nolint:gosec,noctx // fixed binaries from the supervisor's own config; stopped via signals, not a context
	cmd.Dir = c.dir
	// Children never inherit the supervisor's environment, which may hold GH_TOKEN,
	// HF_TOKEN or other credentials of the owner's shell.
	cmd.Env = []string{"PATH=" + childPATH, "LANG=" + childLang}
	for k, v := range c.env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	cmd.Stdout, cmd.Stderr = out, out
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	c.mu.Lock()
	c.cmd = cmd
	c.mu.Unlock()
	c.log.Info("child started", "child", c.name, "pid", cmd.Process.Pid, "sandboxed", c.profile != "")
	return cmd, nil
}

func (c *child) pid() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cmd == nil || c.cmd.Process == nil || c.cmd.ProcessState != nil {
		return 0
	}
	return c.cmd.Process.Pid
}

// run starts the child and waits for it to exit or for ctx to end, then stops it
// with SIGTERM and, after stopIn, SIGKILL.
func (c *child) run(ctx context.Context) error {
	cmd, err := c.start()
	if err != nil {
		return err
	}
	var waitErr error
	done := make(chan struct{})
	go func() { waitErr = cmd.Wait(); close(done) }()
	select {
	case <-done:
		c.log.Warn("child exited", "child", c.name, "err", errString(waitErr))
		if waitErr == nil {
			return errors.New("exited")
		}
		return waitErr
	case <-ctx.Done():
	}
	_ = cmd.Process.Signal(syscall.SIGTERM)
	select {
	case <-done:
	case <-time.After(c.stopIn):
		c.log.Warn("child did not stop in time; killing", "child", c.name)
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		select {
		case <-done:
		case <-time.After(killFallback):
		}
	}
	c.log.Info("child stopped", "child", c.name)
	return nil
}

// supervise restarts the child with exponential backoff until ctx ends.
func (c *child) supervise(ctx context.Context) {
	backoff := time.Second
	for ctx.Err() == nil {
		began := time.Now()
		err := c.run(ctx)
		if ctx.Err() != nil {
			return
		}
		if time.Since(began) > stableAfter {
			backoff = time.Second
		}
		c.log.Warn("restarting child", "child", c.name, "in", backoff.String(), "err", errString(err))
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		backoff = min(backoff*2, maxBackoff)
	}
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return fmt.Sprint(err)
}
