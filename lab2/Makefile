CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra

ftr: sender.cpp receiver.cpp common.hpp
	$(CXX) $(CXXFLAGS) -o ftr sender.cpp receiver.cpp

clean:
	rm -f ftr

.PHONY: clean
