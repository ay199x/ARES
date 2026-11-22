# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""What a picture of the ARM X-Ray shows must not overlap: a checker for the tests.

clashes(canvas) lists every visible text (or value label) that lies over another
text, over a line it does not belong to, or across the outline of a block; a width
number may lie over no wire but its slash, and a value under no arrowhead. What
an item belongs to is the part after the colon of its tags: "wire:PC",
"slash:PC" and "mid:PC" belong to PC, "block:ALU" to the ALU. A label's text lies
in its own box; a text may lie inside any box or shape, or outside it, but not
across its outline.

A text is measured by where its letters reach, not by the box Tk keeps for its
lines: from the baseline up to the height of a capital (or of a small letter when
it has only small letters), and down by a descender when it has one (g, p, y and
the like), in its own font's size. Two texts side by side may touch, as two boxes
may; two texts one over the other keep a small gap between their letters, NAME_GAP
of their size, so that names down a block's edge never run into each other at any
size.

low_contrasts(canvas) lists every visible text, line, mark and outline whose colour
has a contrast under 3 to 1 (the WCAG ratio) against what it lies on: the fill of
the topmost filled shape under it, or the canvas's background.
"""

GAP = 1                             # pixels two things may touch
# Where letters reach from the baseline, in their font's size: a capital, a digit or a tall
# small letter up to TALL, the other small letters up to SHORT; a descender down to DOWN.
TALL, SHORT, DOWN = 0.72, 0.53, 0.22
NAME_GAP = 0.15                     # the least gap between the letters of two texts, in their size
LOW = frozenset("acegmnopqrsuvwxyz.,:;-=+~_ ")      # no taller than a small x
DESCENDING = frozenset("gjpqy,;()[]{}|@$Q_")         # below the baseline


def groups(canvas, item):
    return {tag.split(":", 1)[1] for tag in canvas.gettags(item) if ":" in tag}


def shown(canvas, item):
    if canvas.itemcget(item, "state") == "hidden":
        return False
    kind = canvas.type(item)
    if kind == "text":
        return bool(canvas.itemcget(item, "text").strip())
    if kind == "line":
        return bool(canvas.itemcget(item, "fill"))
    return True


def _measures(canvas, font):
    """(ascent, line height, size) of a font in pixels: its size as the system draws it."""
    call = canvas.tk.call
    ascent = int(call("font", "metrics", font, "-ascent"))
    descent = int(call("font", "metrics", font, "-descent"))
    size = int(call("font", "actual", font, "-size"))
    em = -size if size < 0 else int(size * float(call("tk", "scaling")) + 0.5)
    return ascent, ascent + descent, em


def _letters(canvas, text, font, anchor, y, box, fonts):
    """(left, top, right, bottom) of where the letters of a text in font reach (see the
    module), and the font's size in pixels: box is Tk's box of its lines, y and anchor where
    the program put it (Tk rounds that to a whole pixel to draw it; measured from y, a text
    keeps its distance to the next at every size); fonts keeps what _measures() found."""
    left, top, right, bottom = box
    if font not in fonts:
        fonts[font] = _measures(canvas, font)
    ascent, linespace, em = fonts[font]
    lines = text.split("\n")
    count = max(1, round((bottom - top) / linespace))
    height = count * linespace
    top = y if anchor.startswith("n") else y - height if anchor.startswith("s") else y - height / 2
    first, last = lines[0], lines[-1]
    if count > len(lines):              # broken into more lines: any word may come first or last
        first = last = text
    up = TALL if set(first) - LOW else SHORT
    down = DOWN if set(last) & DESCENDING else 0.0
    return (left, top + ascent - up * em, right,
            top + (count - 1) * linespace + ascent + down * em), em


# Every item of a canvas with what clashes() needs of it, in one call to Tk: asked item by item,
# Tk takes most of the time.
_READ = """set c %s
set found {}
foreach id [$c find all] {
    set kind [$c type $id]
    set more {}
    if {$kind eq "text"} {
        set anchor [$c itemcget $id -anchor]
        set more [list [$c itemcget $id -text] [$c itemcget $id -font] [$c bbox $id] $anchor]
    } elseif {$kind eq "line"} {
        set more [list [$c itemcget $id -fill] [$c itemcget $id -width]]
    }
    set state [$c itemcget $id -state]
    lappend found [list $id $kind $state [$c gettags $id] [$c coords $id] $more]
}
set found"""


class _Items:
    """What clashes() reads of the canvas, read once."""

    def __init__(self, canvas, ignore):
        self.kind, self.tags, self.groups = {}, {}, {}
        self.boxes = []                 # (item, box): every visible text (its letters) and label
        self.ems = {}                   # text item -> its font's size in pixels
        self.lines = []                 # (item, segments, reach, (left, top, right, bottom))
        self.blocks = []                # (item, edges)
        fonts = {}
        split = canvas.tk.splitlist
        for record in split(canvas.tk.eval(_READ % canvas)):
            number, kind, state, tags, coords, more = split(record)
            if state == "hidden":
                continue
            item = int(number)
            more = split(more)
            coords = [float(c) for c in split(coords)]
            if kind == "text" and not more[0].strip() or kind == "line" and not more[0]:
                continue                # nothing to see
            tags = split(tags)
            self.kind[item], self.tags[item] = kind, tags
            self.groups[item] = {tag.split(":", 1)[1] for tag in tags if ":" in tag}
            skipped = ignore is not None and ignore(item)
            if kind == "text" and not skipped and more[2]:
                box = tuple(int(c) for c in split(more[2]))
                box, em = _letters(canvas, more[0], more[1], more[3], coords[1], box, fonts)
                self.boxes.append((item, box))
                self.ems[item] = em
            elif kind == "rectangle" and "label" in tags and not skipped:
                self.boxes.append((item, tuple(coords)))
            if kind == "line":
                points = list(zip(coords[::2], coords[1::2]))
                reach = float(more[1] or 1) / 2
                xs, ys = [x for x, _ in points], [y for _, y in points]
                self.lines.append((item, list(zip(points, points[1:])), reach,
                                   (min(xs) - reach, min(ys) - reach, max(xs) + reach,
                                    max(ys) + reach)))
            elif kind in ("rectangle", "polygon") and "label" not in tags and not skipped:
                if kind == "rectangle":
                    left, top, right, bottom = coords
                    points = [(left, top), (right, top), (right, bottom), (left, bottom)]
                else:
                    points = list(zip(coords[::2], coords[1::2]))
                self.blocks.append((item, list(zip(points, points[1:] + points[:1]))))


def _hidden_by(tags, line_tags):
    """A line of an item's own net may run under its name or value, but not through a width
    number (only its slash may), nor may an arrowhead halfway along cover a value."""
    if "slash" in tags:
        return "slash" not in line_tags
    return "label" in tags and "mid" in line_tags


def _shrunk(box, by):
    left, top, right, bottom = box
    return left + by, top + by, right - by, bottom - by


def _inside(inner, outer):
    return (inner[0] >= outer[0] - GAP and inner[1] >= outer[1] - GAP
            and inner[2] <= outer[2] + GAP and inner[3] <= outer[3] + GAP)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _crosses(segment, box, reach):
    """True when segment, reach pixels thick on each side, passes through box."""
    (x1, y1), (x2, y2) = segment
    left, top, right, bottom = box
    left, top, right, bottom = left - reach, top - reach, right + reach, bottom + reach
    if max(x1, x2) < left or min(x1, x2) > right or max(y1, y2) < top or min(y1, y2) > bottom:
        return False
    if x1 == x2 or y1 == y2:
        return True
    steps = int(max(abs(x2 - x1), abs(y2 - y1))) + 1
    for step in range(steps + 1):
        x = x1 + (x2 - x1) * step / steps
        y = y1 + (y2 - y1) * step / steps
        if left <= x <= right and top <= y <= bottom:
            return True
    return False


def clashes(canvas, gap=GAP, ignore=None):
    """[(what, with what, where)] of every visible text or label that lies over another text,
    over a line of something else, or across the outline of a block (see the module); ignore,
    when given, tells which items to leave out (ignore(item) is True)."""
    items = _Items(canvas, ignore)
    boxes, kinds, groups_of, tags_of = items.boxes, items.kind, items.groups, items.tags
    problems = []
    name = canvas.itemcget

    def where(item):
        """Where item is, in the canvas's own pixels (its box's top left corner)."""
        box = canvas.bbox(item) or (0, 0, 0, 0)
        return (round(box[0]), round(box[1]))

    def said(item):
        if kinds[item] == "text":
            return name(item, "text")
        box = canvas.bbox(item)
        texts = [other for other, other_box in boxes if kinds[other] == "text"
                 and groups_of[other] == groups_of[item] and _inside(other_box, box)]
        return f"[{name(texts[0], 'text')}]" if texts else "[label]"

    for index, (one, box1) in enumerate(boxes):
        label1 = "label" in tags_of[one]
        for other, box2 in boxes[index + 1:]:
            label2 = "label" in tags_of[other]
            if label1 or label2:
                if _inside(box1, box2) or _inside(box2, box1):
                    continue                # a label's text in its own box
                if _overlap(_shrunk(box1, gap), _shrunk(box2, gap)):
                    problems.append((said(one), said(other), where(one)))
                continue
            # Two texts side by side may touch; one over the other, their letters keep a gap.
            if box1[0] + gap < box2[2] - gap and box2[0] + gap < box1[2] - gap:
                room = NAME_GAP * min(items.ems[one], items.ems[other])
                if box1[1] < box2[3] + room and box2[1] < box1[3] + room:
                    problems.append((said(one), said(other), where(one)))
    for item, box in boxes:
        mine = groups_of[item]
        tags = tags_of[item]
        inner = _shrunk(box, gap)
        for line, segments, reach, (left, top, right, bottom) in items.lines:
            if left > inner[2] or right < inner[0] or top > inner[3] or bottom < inner[1]:
                continue
            if mine & groups_of[line] and not _hidden_by(tags, tags_of[line]):
                continue
            if any(_crosses(segment, inner, reach) for segment in segments):
                problems.append((said(item), "line of " + (",".join(sorted(groups_of[line]))
                                                           or "a mark"), where(item)))
                break
    for item, box in boxes:
        mine = groups_of[item]
        for block, edges in items.blocks:
            # A block's own letters keep a pixel more: the corners of a letter's box are empty.
            inner = _shrunk(box, gap + 1 if mine & groups_of[block] else gap)
            if any(_crosses(edge, inner, 0.5) for edge in edges):
                if mine & groups_of[block]:
                    problems.append((said(item), "the outline of its block", where(item)))
                else:
                    problems.append((said(item), "the outline of " +
                                     ",".join(sorted(groups_of[block])), where(item)))
                break
    return problems


# Contrast ------------------------------------------------------------------------------------

def luminance(colour):
    """The relative luminance of "#RRGGBB" (WCAG 2), computed here on its own."""
    def linear(part):
        c = int(part, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(colour[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one, other):
    light, dark = sorted((luminance(one), luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _hex(canvas, colour):
    """A Tk colour as "#RRGGBB"."""
    if colour.startswith("#") and len(colour) == 7:
        return colour.upper()
    r, g, b = (value // 257 for value in canvas.winfo_rgb(colour))
    return f"#{r:02X}{g:02X}{b:02X}"


def _contains(canvas, item, point):
    """True when point lies inside the filled shape item."""
    x, y = point
    coords = canvas.coords(item)
    kind = canvas.type(item)
    if kind == "rectangle":
        left, top, right, bottom = coords
        return left <= x <= right and top <= y <= bottom
    if kind == "oval":
        left, top, right, bottom = coords
        rx, ry = (right - left) / 2, (bottom - top) / 2
        if rx <= 0 or ry <= 0:
            return False
        return ((x - left - rx) / rx) ** 2 + ((y - top - ry) / ry) ** 2 <= 1
    points = list(zip(coords[::2], coords[1::2]))
    inside = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def low_contrasts(canvas, least=3.0):
    """[(what, its colour, what it lies on, the ratio)] of every visible text, line, dot and
    outline of a filled shape whose contrast against what lies under it is under least."""
    items = [item for item in canvas.find_all() if shown(canvas, item)]
    fills = [item for item in items if canvas.type(item) in ("rectangle", "polygon", "oval")
             and canvas.itemcget(item, "fill")]
    background = _hex(canvas, canvas.cget("background"))
    order = {item: number for number, item in enumerate(items)}
    # What things lie on: the filled shapes but the dots, which are marks themselves (two
    # branches that leave a wire at one point draw two dots there).
    shapes = [(order[shape], shape, canvas.bbox(shape), _hex(canvas, canvas.itemcget(shape, "fill")))
              for shape in reversed(fills) if canvas.type(shape) != "oval"]     # the topmost first

    def under(item, point):
        """The colour under point, below item in the stacking order."""
        x, y = point
        for number, shape, (left, top, right, bottom), fill in shapes:
            if number < order[item] and left <= x <= right and top <= y <= bottom \
                    and _contains(canvas, shape, point):
                return fill
        return background

    def said(item):
        if canvas.type(item) == "text":
            return canvas.itemcget(item, "text")
        return f"{canvas.type(item)} {','.join(sorted(groups(canvas, item))) or 'mark'}"

    found = []

    def check(item, colour, point):
        """Note item when colour at point is too faint; True when it is."""
        colour = _hex(canvas, colour)
        lying = under(item, point)
        ratio = contrast(colour, lying)
        if ratio < least:
            found.append((said(item), colour, lying, round(ratio, 2)))
        return ratio < least
    for item in items:
        kind = canvas.type(item)
        if kind == "text":
            left, top, right, bottom = canvas.bbox(item)
            check(item, canvas.itemcget(item, "fill"), ((left + right) / 2, (top + bottom) / 2))
        elif kind == "line":
            coords = canvas.coords(item)
            points = list(zip(coords[::2], coords[1::2]))
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                if (x1, y1) != (x2, y2) and check(item, canvas.itemcget(item, "fill"),
                                                  ((x1 + x2) / 2, (y1 + y2) / 2)):
                    break                   # one note for each line
        elif item in fills:
            left, top, right, bottom = canvas.bbox(item)
            middle = ((left + right) / 2, (top + bottom) / 2)
            outline = canvas.itemcget(item, "outline")
            if kind == "oval":              # a dot: its fill against what it lies on
                check(item, canvas.itemcget(item, "fill"), middle)
            elif outline and outline != canvas.itemcget(item, "fill"):
                check(item, outline, middle)
    return found
