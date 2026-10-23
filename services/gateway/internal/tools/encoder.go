package tools

import (
	"bytes"
	"encoding/json"
	"math"
	"strconv"
)

// obj writes minified JSON with a fixed key order; contracts/tools.md requires
// byte-stable model views so training data and production stay identical.
type obj struct {
	buf   bytes.Buffer
	count int
}

func newObj() *obj {
	o := &obj{}
	o.buf.WriteByte('{')
	return o
}

func (o *obj) key(k string) {
	if o.count > 0 {
		o.buf.WriteByte(',')
	}
	o.count++
	o.buf.Write(quote(k))
	o.buf.WriteByte(':')
}

func (o *obj) str(k, v string) *obj {
	o.key(k)
	o.buf.Write(quote(v))
	return o
}

func (o *obj) num(k string, v float64, dp int) *obj {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return o
	}
	o.key(k)
	o.buf.WriteString(formatNum(v, dp))
	return o
}

func (o *obj) optNum(k string, v *float64, dp int) *obj {
	if v == nil {
		return o
	}
	return o.num(k, *v, dp)
}

func (o *obj) integer(k string, v float64) *obj {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return o
	}
	o.key(k)
	o.buf.WriteString(strconv.FormatInt(int64(math.Round(v)), 10))
	return o
}

func (o *obj) optInt(k string, v *float64) *obj {
	if v == nil {
		return o
	}
	return o.integer(k, *v)
}

func (o *obj) boolean(k string, v bool) *obj {
	o.key(k)
	o.buf.WriteString(strconv.FormatBool(v))
	return o
}

func (o *obj) raw(k string, v []byte) *obj {
	o.key(k)
	o.buf.Write(v)
	return o
}

func (o *obj) bytes() []byte {
	b := append([]byte(nil), o.buf.Bytes()...)
	return append(b, '}')
}

func array(items [][]byte) []byte {
	var b bytes.Buffer
	b.WriteByte('[')
	for i, it := range items {
		if i > 0 {
			b.WriteByte(',')
		}
		b.Write(it)
	}
	b.WriteByte(']')
	return b.Bytes()
}

func numArray(v []float64, dp int) []byte {
	items := make([][]byte, len(v))
	for i, x := range v {
		items[i] = []byte(formatNum(x, dp))
	}
	return array(items)
}

func formatNum(v float64, dp int) string {
	p := math.Pow10(dp)
	r := math.Round(v*p) / p
	if r == 0 {
		r = 0
	}
	return strconv.FormatFloat(r, 'f', -1, 64)
}

func quote(s string) []byte {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(s)
	return bytes.TrimRight(b.Bytes(), "\n")
}

func errorView(code, msg string) string {
	return string(newObj().str("error", code).str("message", msg).bytes())
}
