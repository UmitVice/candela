// Package egress builds the only HTTP client allowed to reach the internet for market
// data. Hosts must be allowlisted and every resolved address must be public, so neither
// a redirect nor DNS rebinding can turn a data fetch into a request against the Mac's
// loopback services or the local network (docs/adr/0008-public-exposure-threat-model.md).
package egress

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/netip"
	"strings"
	"syscall"
	"time"
)

var ErrBlocked = errors.New("egress blocked")

var DefaultAllow = []string{"www.nasdaqtrader.com", "huggingface.co", "*.huggingface.co", "*.hf.co"}

var blocked = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"),
	netip.MustParsePrefix("10.0.0.0/8"),
	netip.MustParsePrefix("100.64.0.0/10"),
	netip.MustParsePrefix("127.0.0.0/8"),
	netip.MustParsePrefix("169.254.0.0/16"),
	netip.MustParsePrefix("172.16.0.0/12"),
	netip.MustParsePrefix("192.0.0.0/24"),
	netip.MustParsePrefix("192.168.0.0/16"),
	netip.MustParsePrefix("198.18.0.0/15"),
	netip.MustParsePrefix("224.0.0.0/4"),
	netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("::/128"),
	netip.MustParsePrefix("::1/128"),
	netip.MustParsePrefix("fc00::/7"),
	netip.MustParsePrefix("fe80::/10"),
	netip.MustParsePrefix("ff00::/8"),
}

func PublicAddr(a netip.Addr) bool {
	a = a.Unmap()
	if !a.IsValid() || a.IsUnspecified() || a.IsLoopback() || a.IsPrivate() || a.IsLinkLocalUnicast() || a.IsMulticast() {
		return false
	}
	for _, p := range blocked {
		if p.Contains(a) {
			return false
		}
	}
	return true
}

type Allowlist []string

func (l Allowlist) Allows(host string) bool {
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	if host == "" {
		return false
	}
	if _, err := netip.ParseAddr(host); err == nil {
		return false
	}
	for _, p := range l {
		p = strings.ToLower(strings.TrimSpace(p))
		if suffix, ok := strings.CutPrefix(p, "*."); ok {
			if strings.HasSuffix(host, "."+suffix) {
				return true
			}
		} else if host == p {
			return true
		}
	}
	return false
}

type guard struct {
	allow Allowlist
	next  http.RoundTripper
}

func (g guard) RoundTrip(req *http.Request) (*http.Response, error) {
	if req.URL.Scheme != "https" || !g.allow.Allows(req.URL.Hostname()) {
		return nil, fmt.Errorf("%w: host not allowlisted", ErrBlocked)
	}
	return g.next.RoundTrip(req)
}

// NewClient returns an HTTPS-only client restricted to the allowlist. The dialer checks
// the address actually being connected to, after DNS resolution.
func NewClient(allow Allowlist, timeout time.Duration) *http.Client {
	dialer := &net.Dialer{
		Timeout:   10 * time.Second,
		KeepAlive: 30 * time.Second,
		Control: func(_, address string, _ syscall.RawConn) error {
			ap, err := netip.ParseAddrPort(address)
			if err != nil || !PublicAddr(ap.Addr()) {
				return fmt.Errorf("%w: non-public address", ErrBlocked)
			}
			return nil
		},
	}
	tr := &http.Transport{
		Proxy:                 nil,
		DialContext:           func(ctx context.Context, n, a string) (net.Conn, error) { return dialer.DialContext(ctx, n, a) },
		ForceAttemptHTTP2:     true,
		MaxIdleConns:          16,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 60 * time.Second,
	}
	return &http.Client{
		Timeout:   timeout,
		Transport: guard{allow: allow, next: tr},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 {
				return errors.New("too many redirects")
			}
			if !allow.Allows(req.URL.Hostname()) {
				return fmt.Errorf("%w: redirect to a host outside the allowlist", ErrBlocked)
			}
			return nil
		},
	}
}
