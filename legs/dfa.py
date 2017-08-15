# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

'''
Finite Automata.
NFA/DFA implementation derived from http://www-bcf.usc.edu/~breichar/teaching/2011cs360/NFAtoDFA.py.

Terminology:
Node: a discrete position in the automaton graph, represented as an integer.
  This is traditionally referred to as a 'state'.
State: the state of the algorithm while matching an input string against an automaton.
  For DFAs, the state is the current node.
  For NFAs, the state is a set of nodes;
    traditionally this is referred to as "simulating the NFA",
    or the NFA being "in multiple states at once".
We make the node/state distinction here so that the code and documentation can be more precise,
at the cost of being less traditional.

An automaton consists of two parts:
* transitions: dictionary of source node to (dictionary of byte to destination).
  * for DFAs, the destination is a single node.
  * for NFAs, the destination is a set of nodes, representing a subset of the next state.
* matchNodeNames: the set of nodes that represent a match, and the corresponding name for each.

The starting state is always 0 for DFAs, and {0} for NFAs.
Additionally, 1 and {1} are always the respective invalid states.
When matching fails, the FA transitions to `invalid`,
where it will continue matching all bytes that are not a transition from `initial`.
This allows the FA to produce a stream of tokens that completely span any input string.

`empty_symbol` is a reserved value (-1 is not part of the byte alphabet)
that represents a nondeterministic jump between NFA nodes.
'''

from collections import defaultdict
from itertools import chain
from typing import *

from pithy.io import errL, errSL
from pithy.iterable import int_tuple_ranges
from pithy.string_utils import prepend_to_nonempty

from .codepoints import codes_desc


DfaState = int
DfaStateTransitions = Dict[int, DfaState]
DfaTransitions = Dict[int, DfaStateTransitions]

empty_symbol = -1 # not a legitimate byte value.



class DFA:
  'Deterministic Finite Automaton.'

  def __init__(self, transitions: DfaTransitions, matchNodeNames: Dict[int, str], literalRules: Dict[str, str]) -> None:
    self.transitions = transitions
    self.matchNodeNames = matchNodeNames
    self.literalRules = literalRules

  @property
  def isEmpty(self) -> bool:
    return not self.transitions

  @property
  def allByteToStateDicts(self) -> Iterable[DfaStateTransitions]: return self.transitions.values()

  @property
  def alphabet(self) -> FrozenSet[int]:
    a: Set[int] = set()
    a.update(*(d.keys() for d in self.allByteToStateDicts))
    a.discard(empty_symbol)
    return cast(FrozenSet[int], frozenset(a)) # mypy bug.

  @property
  def allSrcNodes(self) -> FrozenSet[int]: return frozenset(self.transitions.keys())

  @property
  def allDstNodes(self) -> FrozenSet[int]:
    s: Set[int] = set()
    s.update(*(self.dstNodes(node) for node in self.allSrcNodes))
    return frozenset(s)

  @property
  def allNodes(self) -> FrozenSet[int]: return self.allSrcNodes | self.allDstNodes

  @property
  def terminalNodes(self) -> FrozenSet[int]: return frozenset(n for n in self.allNodes if not self.transitions.get(n))

  @property
  def matchNodes(self) -> FrozenSet[int]: return frozenset(self.matchNodeNames.keys())

  @property
  def nonMatchNodes(self) -> FrozenSet[int]: return self.allNodes - self.matchNodes

  @property
  def preMatchNodes(self) -> FrozenSet[int]:
    if self.isEmpty:
      return frozenset() # empty.
    matchNodes = self.matchNodes
    nodes: Set[int] = set()
    remaining = {0}
    while remaining:
      node = remaining.pop()
      assert node not in nodes
      if node in matchNodes: continue
      nodes.add(node)
      remaining.update(self.dstNodes(node) - nodes)
    return frozenset(nodes)

  @property
  def postMatchNodes(self) -> FrozenSet[int]:
    matchNodes = self.matchNodes
    nodes: Set[int] = set()
    remaining = set(matchNodes)
    while remaining:
      node = remaining.pop()
      for dst in self.dstNodes(node):
        if dst not in matchNodes and dst not in nodes:
          nodes.add(dst)
          remaining.add(dst)
    return frozenset(nodes)

  @property
  def ruleNames(self) -> FrozenSet[str]: return frozenset(self.matchNodeNames.values())

  def describe(self, label=None) -> None:
    errL(label or type(self).__name__, ':')
    errL(' matchNodeNames:')
    for node, name in sorted(self.matchNodeNames.items()):
      errL(f'  {node}: {name}')
    errL(' transitions:')
    for src, d in sorted(self.transitions.items()):
      errL(f'  {src}:{prepend_to_nonempty(" ", self.matchNodeNames.get(src, ""))}')
      dst_bytes: DefaultDict[int, Set[int]]  = defaultdict(set)
      for byte, dst in d.items():
        dst_bytes[dst].add(byte)
      dst_sorted_bytes = [(dst, sorted(byte_set)) for (dst, byte_set) in dst_bytes.items()]
      for dst, bytes_list in sorted(dst_sorted_bytes, key=lambda p: p[1]):
        byte_ranges = int_tuple_ranges(bytes_list)
        errL('    ', codes_desc(byte_ranges), ' ==> ', dst, prepend_to_nonempty(': ', self.matchNodeNames.get(dst, '')))
    errL()

  def describe_stats(self, label=None) -> None:
    errL(label or type(self).__name__, ':')
    errSL('  matchNodeNames:', len(self.matchNodeNames))
    errSL('  nodes:', len(self.transitions))
    errSL('  transitions:', sum(len(d) for d in self.transitions.values()))
    errL()
  def dstNodes(self, node: int) -> FrozenSet[int]:
    return frozenset(self.transitions[node].values())

  def advance(self, state: int, byte: int) -> int:
    return self.transitions[state][byte]

  def match(self, text: str, start: int=0) -> Optional[str]:
    text_bytes = text.encode('utf8')
    state = start
    for byte in text_bytes:
      try: state = self.advance(state, byte)
      except KeyError: return None
    return self.matchNodeNames.get(state)



def minimizeDFA(dfa: DFA) -> DFA:
  '''
  Optimize a DFA by coalescing redundant states.
  sources:
  * http://www.cs.sun.ac.za/rw711/resources/dfa-minimization.pdf.
  * https://en.wikipedia.org/wiki/DFA_minimization.
  * https://www.ics.uci.edu/~eppstein/PADS/PartitionRefinement.py
  '''
  alphabet = dfa.alphabet
  # start with a rough partition; match nodes are all distinct from each other,
  # and non-match nodes form an additional distinct set.
  init_sets = [{n} for n in dfa.matchNodes] + [set(dfa.nonMatchNodes)]

  sets = { id(s): s for s in init_sets }
  partition = { n: s for s in sets.values() for n in s }

  rev_transitions: DefaultDict[int, DefaultDict[int, Set[int]]] = defaultdict(lambda: defaultdict(set))
  for src, d in dfa.transitions.items():
    for char, dst in d.items():
      rev_transitions[dst][char].add(src)

  def refine(refining_set: Set[int]) -> List[Tuple[Set[int], Set[int]]]:
    '''
    Given refining set B,
    Refine each set A in the partition to a pair of sets: A & B and A - B.
    Return a list of pairs for each changed set;
    one of these is a new set, the other is the mutated original.
    '''
    part_sets_to_intersections: DefaultDict[int, Set[int]] = defaultdict(set)
    set_pairs = []
    for node in refining_set:
      s = partition[node]
      part_sets_to_intersections[id(s)].add(node)
    for id_s, intersection in part_sets_to_intersections.items():
      s = sets[id_s]
      if intersection != s:
        sets[id(intersection)] = intersection
        for x in intersection:
          partition[x] = intersection
        s -= intersection
        set_pairs.append((intersection, s))
    return set_pairs

  remaining = list(init_sets) # distinguishing sets used to refine the partition.
  while remaining:
    a = remaining.pop() # a partition.
    for char in alphabet:
      # find all nodes `m` that transition via `char` to any node `n` in `a`.
      dsts = set(chain.from_iterable(rev_transitions[node][char] for node in a))
      #dsts_brute = [node for node in partition if dfa.transitions[node].get(char) in a] # brute force version is slow.
      #assert set(dsts_brute) == dsts
      len_dsts = len(dsts)
      if len_dsts == 0 or len_dsts == len(partition): continue # no refinement.
      for new, old in refine(dsts):
        if len(new) < len(old): # prefer new.
          if new not in remaining: remaining.append(new)
          elif old not in remaining: remaining.append(old)
        else: # prefer old.
          if old not in remaining: remaining.append(old)
          elif new not in remaining: remaining.append(new)

  mapping = {}
  for new_node, part in enumerate(sorted(sorted(p) for p in partition.values())):
    for old_node in part:
      mapping[old_node] = new_node

  transitions: DefaultDict[int, Dict[int, int]] = defaultdict(dict)
  for old_node, old_d in dfa.transitions.items():
    new_d = transitions[mapping[old_node]]
    for char, old_dst in old_d.items():
      new_dst = mapping[old_dst]
      try:
        existing = new_d[char]
        if existing != new_dst:
          exit(f'inconsistency in minimized DFA: src state: {old_node}->{new_node}; char: {char!r}; dst state: {old_dst}->{new_dst} != ?->{existing}')
      except KeyError:
        new_d[char] = new_dst

  matchNodeNames = { mapping[old] : name for old, name in dfa.matchNodeNames.items() }
  return DFA(transitions=dict(transitions), matchNodeNames=matchNodeNames, literalRules=dfa.literalRules)
