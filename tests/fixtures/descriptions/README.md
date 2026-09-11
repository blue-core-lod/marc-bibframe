BIBFRAME descriptions copied from LC's own bibframe2marc test data
(`rules/test/data/` in https://github.com/lcnetdev/bibframe2marc), which is
CC0 like the rest of that repository.

Each one is here because it caught a way the striper in
`marc_bibframe._striping` can be unfaithful to marc2bibframe2's own RDF/XML:

* `111.xml` -- a `madsrdf:elementList` held in an `rdf:parseType="Collection"`.
  Rebuilt as an rdf:first/rdf:rest chain, the rules cannot see its members and
  the 111 loses its `$a`.
* `240.xml` -- a node typed both `bf:Hub` and `bf:Arrangement`. Named after the
  specific class rather than the general one, the 240 rule never fires.
* `306-02.xml` -- an `xsd:duration` of `PT00H31M00S`. rdflib normalizes typed
  literals as it parses unless told not to, which turns the 306 into `31`.
