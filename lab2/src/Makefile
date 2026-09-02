CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra
SRC = ftr.cpp methods/nak.cpp
HDR = common.hpp
ftr: $(SRC) $(HDR)
	$(CXX) $(CXXFLAGS) -o ftr $(SRC)
clean:
	rm -f ftr
.PHONY: clean
